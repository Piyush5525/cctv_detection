"""Replays ONE stored clip through the REAL detectors and the SAME EventCapturePipeline the live cameras use.

Used by the demo trigger (api/services/demo_trigger.py) and by scripts/demo_clips_check.py. Nothing is forced:
if a detector does not fire on the clip, the report says so (peak score, nearest miss and which rule blocked it)
and no event or incident exists. Time is video time (frame_index / fps) mapped onto a wall-clock origin in the
recent past, so replays are deterministic and event_start is never in the future.

Per sampled frame: fire/crash (when requested) use the existing registry detectors with the live floor; the action
detectors go through ActionRuntime (shared pose pass, per-detector pipelines, overlay best frame, scalar signals).
"""
from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

import cv2

from api.core.config import settings
from api.services.action_detectors import ACTION_NAMES
from api.services.action_detectors.runtime import ActionRuntime
from api.services.event_capture import EventCapturePipeline, RingBuffer
from api.services.frame_sampler import TimeBasedSampler

_registry = None


def _fire_crash_registry():
    global _registry
    if _registry is None:
        from api.services.detector_interface import DetectorRegistry
        _registry = DetectorRegistry(confidence_floor=settings.FIRE_CRASH_CONFIDENCE_FLOOR)
    return _registry


@dataclass
class ReplayEvent:
    detector: str
    category: str
    start_s: float
    end_s: float
    peak_score: float
    threshold: float
    confirmations: str
    signals: dict
    experimental: bool
    evidence: dict = field(default_factory=dict)
    incident: Optional[dict] = None


@dataclass
class ReplayReport:
    clip: str
    duration_s: float
    fps: float
    size: tuple
    wall_s: float = 0.0
    events: list = field(default_factory=list)            # ReplayEvent, in time order
    detectors: dict = field(default_factory=dict)         # name -> {fired, peak_score, threshold, near_miss..., blocked_by}
    quarantined: list = field(default_factory=list)

    def fired(self, name: str) -> bool:
        return any(e.detector == name for e in self.events)

    def first_event(self, name: str) -> Optional[ReplayEvent]:
        return next((e for e in self.events if e.detector == name), None)


def _detector_for_category(category: str) -> str:
    return {"fire": "fire", "crash": "crash", "fall": "fall", "assault": "violence", "snatching": "snatch"}[category]


def replay_clip(path: Path, camera_id: str, action_names=(), fire_crash=False, on_event: Optional[Callable] = None,
                max_seconds: Optional[float] = None, clip_fn=None, pose=None) -> ReplayReport:
    """on_event(camera_id, ev, evidence) -> Optional[dict]: called from the encoder thread with the finished event
    (e.g. to create the real incident); a returned incident dict is attached to the ReplayEvent. Without it the
    evidence files are still written (under settings.EVIDENCE_ROOT_V2) but no incident exists."""
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise FileNotFoundError(f"clip not readable: {path.name}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    size = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    duration = n_frames / fps if n_frames else 0.0
    report = ReplayReport(clip=path.name, duration_s=round(duration, 2), fps=round(fps, 2), size=size)
    base = datetime.now(timezone.utc) - timedelta(seconds=(max_seconds or duration) + 10)
    names = [n for n in action_names if n in ACTION_NAMES]
    events: list = []

    def ready(cam, ev, evidence):
        detector = _detector_for_category(ev.category)
        rec = ReplayEvent(detector=detector, category=ev.category, start_s=round((ev.event_start - base).total_seconds(), 2),
                          end_s=round((ev.last_detection_at - base).total_seconds(), 2), peak_score=round(ev.peak_score or max(
                              (fs.confidence for fs in ev.frames), default=0.0), 3),
                          threshold=ev.threshold_applied, confirmations=ev.confirmations, signals=dict(ev.signals), experimental=ev.experimental,
                          evidence={k: v for k, v in evidence.items() if k in ("incident_id", "best_frame_path", "annotated_frame_path", "thumbnail_path", "clip_path",
                                                                              "video_offset_start_s", "video_offset_end_s")})
        if on_event is not None:
            rec.incident = on_event(cam, ev, evidence)
        events.append(rec)

    def quarantined(cam, category, reason, event_start, partial):
        report.quarantined.append({"category": category, "reason": reason})

    buf = RingBuffer(settings.PRE_EVENT_SECONDS)
    kwargs = {"clip_fn": clip_fn, **({"pose": pose} if pose is not None else {})}
    runtime = ActionRuntime(camera_id, names, ready, quarantined, buf, **kwargs) if names else None
    if runtime is not None:
        runtime.record = True
    main = EventCapturePipeline(camera_id, ready, quarantined, shared_pre_buffer=buf) if fire_crash else None
    registry = _fire_crash_registry() if fire_crash else None
    sampler = TimeBasedSampler(fps, settings.SAMPLE_INTERVAL_S)
    fc_stats = {n: {"peak": 0.0, "hits": 0, "evaluated": 0} for n in ("fire", "crash")}

    t0, idx, ts = time.perf_counter(), 0, base
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        t = idx / fps
        if max_seconds is not None and t > max_seconds:
            break
        ts = base + timedelta(seconds=t)
        buf.add(frame, ts)
        if main is not None:
            main.add_raw_frame(frame, ts, t)
        if runtime is not None:
            runtime.add_raw_frame(frame, ts, t)
        if main is not None and sampler.should_process(idx):
            category, conf, boxes, det = None, 0.0, [], None
            h, w = frame.shape[:2]
            scale = min(1.0, settings.DETECT_MAX_WIDTH / w)
            small = frame if scale == 1 else cv2.resize(frame, (int(w * scale), int(h * scale)))
            for d in registry.all():
                r = d.detect(small)
                st = fc_stats[d.name]
                st["evaluated"] += 1
                st["peak"] = max(st["peak"], float(r.confidence or 0.0))
                if r.detection and r.confidence >= settings.FIRE_CRASH_CONFIDENCE_FLOOR:
                    st["hits"] += 1
                    if det is None or r.confidence > conf:
                        category, conf, det = d.name, float(r.confidence), (d, r)
                        boxes = [{"label": b.get("class", category), "confidence": b.get("confidence", conf),
                                  "box": [round(float(v) / scale, 2) for v in b.get("box", (0, 0, 0, 0))]} for b in r.boxes]
            main.feed_detection(frame, ts, category, conf if category else 0.0, boxes if category else [],
                                f"yolov8-{det[0].name}" if det else "none", Path(det[0].weights_file).name if det and det[0].weights_file else "none",
                                det[0].threshold if det else settings.FIRE_CRASH_CONFIDENCE_FLOOR,
                                det[0].weights_file if det else None, det[0].weights_sha256 if det else None, video_offset_s=t)
        if runtime is not None:
            runtime.process(frame, t, ts, t)
        idx += 1
    cap.release()
    end = ts + timedelta(seconds=0.01)
    for p in ([main] if main else []) + (list(runtime.pipelines.values()) if runtime else []):
        p.flush(end)
    for p in ([main] if main else []) + (list(runtime.pipelines.values()) if runtime else []):
        p._encode_queue.join()
        p.close()
    report.wall_s = round(time.perf_counter() - t0, 1)
    report.events = sorted(events, key=lambda e: e.start_s)

    # per-detector summary (what fired, nearest miss, which rule blocked it)
    if runtime is not None:
        by: dict = {}
        for name, _ts, _off, res in runtime.verdicts:
            by.setdefault(name, []).append(res)
        for d in runtime.engine.detectors:
            res = by.get(d.name, [])
            blocked = Counter()
            for r in res:
                for b in (r.signals.get("blocked_by") or []) if isinstance(r.signals.get("blocked_by"), list) else []:
                    blocked[b.split(" (")[0] if d.name == "snatch" and b.startswith("no sudden") else b] += 1
                if d.name == "violence" and r.signals.get("gate_reason"):
                    blocked["gate: " + r.signals["gate_reason"]] += 1
            if d.name == "violence":
                scored = [r for r in res if r.signals.get("clip_score") is not None]
                peak = max((r.signals["clip_score"] for r in scored), default=0.0)
                best = max(scored, key=lambda r: r.signals["clip_score"], default=None)
                extra = {"clip_calls": d.clip_calls, "gate_open_evaluations": len(scored), "evaluations": len(res),
                         "best_clip_label": best.signals.get("clip_label") if best else None}
            else:
                best = max(res, key=lambda r: r.score, default=None)
                peak = best.score if best else 0.0
                extra = {"evaluations": len(res)}
            report.detectors[d.name] = {"fired": report.fired(d.name), "peak_score": round(float(peak), 3), "threshold": d.threshold,
                                        "near_miss_signals": (best.signals if best else {}) if not report.fired(d.name) else {},
                                        "blocked_by": blocked.most_common(5), **extra}
        runtime.engine  # keep a reference for readers
    if fire_crash:
        for n, st in fc_stats.items():
            report.detectors[n] = {"fired": report.fired(n), "peak_score": round(st["peak"], 3), "threshold": settings.FIRE_CRASH_CONFIDENCE_FLOOR,
                                   "evaluations": st["evaluated"], "frames_above_floor": st["hits"]}
    return report
