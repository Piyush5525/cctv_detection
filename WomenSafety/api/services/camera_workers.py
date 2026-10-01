"""Latest-frame multi-camera workers for CCTV and demo phone streams."""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import cv2

from api.core.config import settings
from api.models.camera import all_cameras, get_camera, resolve_stream_source, stream_reachable
from api.models.incident_v2 import SourceKind
from api.services import incident_service_v2 as incidents
from api.services.detector_interface import DetectorRegistry
from api.services.event_capture import EventCapturePipeline
from api.services.frame_sampler import RealtimeFrameGate
from api.services.phone_location import location_fields, resolve_location


def _weights(name: str):
    path = Path(__file__).parent.parent.parent / "models" / name
    if not path.exists():
        return str(path), None
    import hashlib
    return str(path), hashlib.sha256(path.read_bytes()).hexdigest()


_URL_PREFIXES = ("rtsp://", "rtsp", "http://", "https://", "rtmp://")


def _open_capture(camera):
    """Returns (cap_or_None, kind, error). Never raises: an unresolved env:
    source, a bad path or an unreachable stream just yields an error string
    so the worker marks the camera offline and retries (fix pass item 11)."""
    try:
        source = resolve_stream_source(camera)
    except Exception as exc:  # e.g. env: var unset
        return None, "unresolved", f"stream source unresolved: {exc}; will retry"
    source = source.strip() if isinstance(source, str) else source
    if isinstance(source, str) and source.isdigit():
        source = int(source)  # device index, e.g. webcam "0"
    if isinstance(source, int):
        return cv2.VideoCapture(source), "device", None
    if source.lower().startswith(_URL_PREFIXES):
        if not stream_reachable(source, settings.CAMERA_OPEN_TIMEOUT_S):
            return None, "stream", "stream unreachable"
        ms = int(settings.CAMERA_OPEN_TIMEOUT_S * 1000)
        try:
            cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG, [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, ms, cv2.CAP_PROP_READ_TIMEOUT_MSEC, ms])
        except Exception:
            cap = cv2.VideoCapture(source)
        return cap, "stream", None
    path = Path(source)
    if not path.is_absolute():
        path = Path(__file__).parent.parent.parent / path
    return cv2.VideoCapture(str(path)), "file", None


class CameraWorker:
    """Two threads per camera (fix pass item 11): a dedicated READER keeps
    only the latest frame (so a slow detector never lets a stream buffer
    build up), and a PROCESSOR that always works on the newest frame."""

    def __init__(self, camera, registry: DetectorRegistry, detector_lock: threading.Lock):
        self.camera, self.registry, self.detector_lock = camera, registry, detector_lock
        self._cond, self._stop = threading.Condition(), threading.Event()
        self._latest = None          # (frame, captured_monotonic, seq)
        self._seq = 0
        self._last_boxes = []
        self.last_frame_at: Optional[float] = None
        self.status, self.error = "offline", None
        self.effective_fps, self.frames_read = 0.0, 0
        self.latency_s: Optional[float] = None  # capture -> detection finished, EMA
        self.reader = threading.Thread(target=self._read_loop, name=f"camera-read-{camera.camera_id}", daemon=True)
        self.thread = threading.Thread(target=self._process_loop, name=f"camera-proc-{camera.camera_id}", daemon=True)
        self.gate = RealtimeFrameGate(settings.SAMPLE_INTERVAL_S, label=camera.camera_id)
        self.pipeline = EventCapturePipeline(camera.camera_id, self._incident_ready, self._quarantine)

    def start(self):
        self.reader.start(); self.thread.start()

    def stop(self):
        self._stop.set()
        with self._cond: self._cond.notify_all()
        self.reader.join(timeout=3); self.thread.join(timeout=3)

    def snapshot(self, annotated=True):
        with self._cond:
            latest = self._latest
            boxes = list(self._last_boxes) if annotated else []
        if latest is None: return None
        frame = latest[0].copy()
        for box in boxes:
            try:
                x1, y1, x2, y2 = map(int, box["box"])
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
                cv2.putText(frame, f"{box['label']} {box['confidence']:.2f}", (x1, max(16, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, .55, (0, 0, 255), 2)
            except Exception: pass
        return frame

    def detail(self):
        age = None if self.last_frame_at is None else round(time.time() - self.last_frame_at, 2)
        return {"camera_id": self.camera.camera_id, "camera_name": self.camera.display_name,
                "camera_type": self.camera.camera_type, "location_basis": self.camera.location_basis,
                "status": self.status, "last_frame_age_s": age,
                "effective_fps": round(self.gate.effective_fps, 2), "frames_read": self.frames_read,
                "latency_s": None if self.latency_s is None else round(self.latency_s, 3), "error": self.error,
                **location_fields(self.camera, resolve_location(self.camera))}

    def _incident_ready(self, camera_id, ev, evidence):
        # Replayed sample files are never labelled live (fix pass item 4).
        source = SourceKind.TEST_REPLAY if self.camera.sample else SourceKind.LIVE
        incidents.handle_finished_event(camera_id, ev, evidence, source=source)

    def _quarantine(self, *args): incidents.handle_encode_failure(*args)

    def _read_loop(self):
        backoff = settings.CAMERA_RECONNECT_INITIAL_S
        while not self._stop.is_set():
            if resolve_location(self.camera) is None:  # no GPS fix (mode != fixed) and no valid .env coordinates: stay offline
                self.status, self.error = "offline", f"location not configured: {self.camera.location_error or 'no acceptable GPS fix and no fixed coordinates'}"
                self._stop.wait(backoff); backoff = min(backoff * 2, settings.CAMERA_RECONNECT_MAX_S); continue
            cap, kind, error = _open_capture(self.camera)
            if cap is None or not cap.isOpened():
                self.status, self.error = "offline", error or "stream unreachable"
                if cap is not None: cap.release()
                self._stop.wait(backoff); backoff = min(backoff * 2, settings.CAMERA_RECONNECT_MAX_S); continue
            self.status, self.error, backoff = "online", None, settings.CAMERA_RECONNECT_INITIAL_S
            frame_period = (1.0 / (cap.get(cv2.CAP_PROP_FPS) or 25.0)) if kind == "file" else 0.0
            next_due = time.monotonic()
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    self.status, self.error = "offline", "stream lost; reconnecting"
                    break
                if frame_period:  # pace file replays at native fps
                    next_due += frame_period
                    delay = next_due - time.monotonic()
                    if delay > 0: self._stop.wait(delay)
                    else: next_due = time.monotonic()
                with self._cond:
                    self._seq += 1
                    self._latest = (frame, time.monotonic(), self._seq)
                    self.last_frame_at, self.frames_read = time.time(), self.frames_read + 1
                    self._cond.notify_all()
            cap.release()
            if kind == "file": continue  # loop the replay immediately
            self._stop.wait(backoff); backoff = min(backoff * 2, settings.CAMERA_RECONNECT_MAX_S)

    def _process_loop(self):
        last_seq = 0
        while not self._stop.is_set():
            with self._cond:
                while self._latest is None or self._latest[2] == last_seq:
                    if self._stop.is_set(): return
                    self._cond.wait(0.5)
                original, captured, last_seq = self._latest
            now, ts = time.time(), datetime.now(timezone.utc)
            self.pipeline.add_raw_frame(original, ts)
            if self.gate.should_process(now):
                detection = self._detect(original)
                self.pipeline.feed_detection(original, ts, **detection)
                with self._cond: self._last_boxes = detection["boxes"]
                age = time.monotonic() - captured
                self.latency_s = age if self.latency_s is None else 0.8 * self.latency_s + 0.2 * age
            else:
                self._stop.wait(0.005)

    def _detect(self, original):
        h, w = original.shape[:2]
        scale = min(1.0, settings.DETECT_MAX_WIDTH / w)
        frame = original if scale == 1 else cv2.resize(original, (int(w * scale), int(h * scale)))
        best = None
        with self.detector_lock:
            for detector in self.registry.all():
                result = detector.detect(frame)
                if result.detection and result.confidence >= settings.FIRE_CRASH_CONFIDENCE_FLOOR and (best is None or result.confidence > best[1].confidence):
                    best = (detector, result)
        if best is None:
            return {"category": None, "confidence": 0.0, "boxes": [], "detector_source": "none", "model_name": "none", "threshold_applied": settings.FIRE_CRASH_CONFIDENCE_FLOOR, "weights_file": None, "weights_sha256": None}
        detector, result = best
        category = "fire" if detector.name == "fire" else "crash"
        boxes = []
        for item in result.boxes:
            box = [round(float(v) / scale, 2) for v in item.get("box", (0, 0, 0, 0))]
            boxes.append({"label": item.get("class", category), "confidence": item.get("confidence", result.confidence), "box": box})
        file, sha = _weights("best_nano_111.pt" if detector.name == "fire" else "crash_best.pt")
        return {"category": category, "confidence": result.confidence, "boxes": boxes, "detector_source": f"yolov8-{detector.name}", "model_name": Path(file).name, "threshold_applied": detector.threshold, "weights_file": file, "weights_sha256": sha}


class CameraWorkerManager:
    def __init__(self): self.workers = {}; self.registry = None; self.detector_lock = threading.Lock()
    def start(self):
        if not settings.LIVE_CAMERA_WORKERS_ENABLED or self.workers: return
        # Fix pass item 3: only phone cameras auto-start unless
        # SAMPLE_CAMERA_WORKERS_ENABLED=true. No detector weights are loaded
        # when there is nothing to run.
        cameras = [c for c in all_cameras() if c.enabled and (c.camera_type == "phone" or settings.SAMPLE_CAMERA_WORKERS_ENABLED)]
        if not cameras:
            print("camera workers: no phone cameras registered; no workers started")
            return
        self.registry = DetectorRegistry(confidence_floor=settings.FIRE_CRASH_CONFIDENCE_FLOOR)
        for camera in cameras:
            worker = CameraWorker(camera, self.registry, self.detector_lock); self.workers[camera.camera_id] = worker; worker.start()
    def stop(self):
        for worker in list(self.workers.values()): worker.stop()
        self.workers.clear()
    def status(self): return {"cameras": [worker.detail() for worker in self.workers.values()]}
    def frame(self, camera_id):
        worker = self.workers.get(camera_id)
        return worker.snapshot() if worker else None


camera_workers = CameraWorkerManager()
