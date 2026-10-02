"""Create a clearly-labelled test replay incident from a stored sample clip.

Fix pass item 9: the first frame of data/fire.mp4 is pure black, so the old
trigger produced a black best frame. We now scan the stored clip once per
category for the frame the real fire/crash detector scores highest (falling
back to the brightest frame after 2 s if the detector finds nothing), cache
that choice (deterministic), and draw the REAL detection boxes/confidence on
it. Either way the incident evidence note says "synthetic demo trigger".
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import threading

import cv2

from api.core.config import settings
from api.models.incident_v2 import SourceKind
from api.services.event_capture import EventCapturePipeline
from api.services import audit
from api.services import incident_service_v2 as incidents

class DemoUnavailable(Exception):
    """The requested demo category cannot run right now (clip missing, detector did not fire, ...). The route maps it
    to HTTP 409 with this message; nothing is forced."""


SAMPLES = {"fire": Path("data/fire.mp4"), "road_accident": Path("data/crash.mp4"), "crash": Path("data/crash.mp4")}
SCAN_STEP_S, SCAN_MAX_S, MIN_START_S = 1.0, 40.0, 2.0
_ROOT = Path(__file__).parent.parent.parent
_picked: dict = {}
_pick_lock = threading.Lock()
_registry = None


def _detectors():
    global _registry
    if _registry is None:
        from api.services.detector_interface import DetectorRegistry
        _registry = DetectorRegistry(confidence_floor=0.0)
    return _registry


def _pick_frame(source: Path, mapped: str):
    """Returns dict(frame, boxes, confidence, real_detection, t_s, detector)."""
    with _pick_lock:
        if mapped in _picked:
            return _picked[mapped]
        cap = cv2.VideoCapture(str(_ROOT / source))
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        detector = _detectors().get("fire" if mapped == "fire" else "crash")
        best, brightest = None, None
        t = 0.0 if mapped == "crash" else MIN_START_S
        while t <= SCAN_MAX_S and (not total or t * fps < total):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
            ok, frame = cap.read()
            if not ok:
                break
            brightness = float(frame.mean())
            if t >= MIN_START_S or mapped == "crash":
                if brightness > 10 and (brightest is None or brightness > brightest["brightness"]):
                    brightest = {"frame": frame.copy(), "brightness": brightness, "t_s": t}
                if detector is not None:
                    r = detector.detect(frame)
                    if r.detection and r.boxes and (best is None or r.confidence > best["confidence"]):
                        best = {"frame": frame.copy(), "confidence": float(r.confidence), "boxes": r.boxes, "t_s": t}
            t += SCAN_STEP_S
        cap.release()
        if best:
            chosen = {**best, "real_detection": True, "detector": detector}
        elif brightest:
            f = brightest["frame"]
            chosen = {"frame": f, "confidence": .99, "t_s": brightest["t_s"], "real_detection": False, "detector": detector,
                      "boxes": [{"class": mapped, "confidence": .99, "box": [0, 0, f.shape[1], f.shape[0]]}]}
        else:
            raise RuntimeError(f"stored sample clip unavailable or empty: {source}")
        _picked[mapped] = chosen
        return chosen


def _real_skeleton_boxes(frame):
    """Skeletons from the real pose model (already in the repo) for ONE frame, as skeleton-only overlay entries; [] if the model is
    unavailable or finds no person. Drawn only into the annotated frame, never stored as data. Not a detector of any category."""
    try:
        from api.services.action_detectors.pose import get_pose_model
        model = get_pose_model()
        if model is None:
            return []
        res = model(frame, verbose=False, conf=settings.ACTION_POSE_CONF, classes=[0])[0]
        if res.keypoints is None or res.boxes is None or len(res.boxes) == 0:
            return []
        out = []
        xy, kc, xyxy = res.keypoints.xy.cpu().numpy(), res.keypoints.conf.cpu().numpy(), res.boxes.xyxy.cpu().numpy()
        for i in range(len(xyxy)):
            if int((kc[i] >= 0.3).sum()) < 8:
                continue
            out.append({"label": "", "confidence": 0.0, "box": [float(v) for v in xyxy[i]], "skeleton_only": True,
                        "keypoints": [[float(x), float(y), float(c)] for (x, y), c in zip(xy[i], kc[i])]})
        return out
    except Exception:
        return []


def trigger_action_incident(camera_id: str, category: str):
    """fall / violence (assault) / snatching: replay the provided clip through the REAL detector and the SAME
    EventCapturePipeline (api/services/clip_replay.py). Returns the first incident created; if the detector does not
    fire, says so plainly and creates nothing."""
    from api.services import demo_clips
    from api.services.clip_replay import replay_clip
    category = demo_clips.ALIASES.get(category, category)
    enabled, reason = demo_clips.availability(category)
    if not enabled:
        raise DemoUnavailable(reason)
    detector, clip, label = demo_clips.ACTION_DEMO[category]
    created = []

    def on_event(cam, ev, evidence):
        a, b = evidence.get("video_offset_start_s"), evidence.get("video_offset_end_s")
        span = f"{a:.1f}-{b:.1f} s" if a is not None and b is not None else "clip"
        note = (f"synthetic demo trigger: replay of {clip} ({span}) through the real {detector} detector; "
                f"peak score {ev.peak_score:.2f} vs threshold {ev.threshold_applied}; EXPERIMENTAL")
        inc = incidents.handle_finished_event(cam, ev, evidence, source=SourceKind.TEST_REPLAY, evidence_note=note)
        if inc:
            created.append(inc.to_dict())
            return inc.to_dict()
        return None

    report = replay_clip(_ROOT / clip, camera_id, action_names=[detector], on_event=on_event)
    d = report.detectors.get(detector, {})
    if not created:
        if report.events or report.quarantined:
            raise DemoUnavailable(f"the {label} detector fired but the event was quarantined (camera has no usable location, or evidence could not be built)")
        raise DemoUnavailable(f"the {label} detector did not fire on the sample clip this time (peak score {d.get('peak_score', 0)} vs threshold "
                              f"{d.get('threshold', '?')}); no incident was created")
    audit.record("demo_trigger", f"{category} on {camera_id}: {len(created)} incident(s) from the real {detector} detector")
    return created[0]


def trigger_demo_incident(camera_id: str, category: str):
    from api.services import demo_clips
    if demo_clips.ALIASES.get(category, category) in demo_clips.ACTION_DEMO:
        return trigger_action_incident(camera_id, category)
    source = SAMPLES.get(category)
    if source is None:
        raise ValueError("category must be fire, crash, road_accident, fall, violence (assault) or snatching")
    mapped = "crash" if category in {"crash", "road_accident"} else category
    pick = _pick_frame(source, mapped)
    frame, detector = pick["frame"], pick["detector"]
    boxes = [{"label": b.get("class", mapped), "confidence": float(b.get("confidence", pick["confidence"])), "box": list(b["box"])} for b in pick["boxes"]]
    note = (f"synthetic demo trigger: stored frame at {pick['t_s']:.0f}s of {source.as_posix()}, "
            + ("boxes/confidence from a real detector run on this frame" if pick["real_detection"]
               else "no detector hit on any scanned frame; full-frame placeholder box, fixed 0.99 confidence"))
    created = []

    def ready(cam, event, evidence):
        incident = incidents.handle_finished_event(cam, event, evidence, source=SourceKind.TEST_REPLAY, evidence_note=note)
        if incident:
            created.append(incident.to_dict())

    pipeline = EventCapturePipeline(camera_id, ready, lambda *args: incidents.handle_encode_failure(*args))
    now = datetime.now(timezone.utc)
    detector_source = f"demo-trigger/{'yolov8-' + detector.name if pick['real_detection'] and detector else 'placeholder'}"
    model_name = Path(detector.weights_file).name if pick["real_detection"] and detector and detector.weights_file else "stored-sample"
    for index in range(3):
        ts = now + timedelta(seconds=index)
        pipeline.add_raw_frame(frame, ts)
        pipeline.feed_detection(frame, ts, mapped, pick["confidence"], boxes, detector_source, model_name,
                                settings.FIRE_CRASH_CONFIDENCE_FLOOR,
                                detector.weights_file if pick["real_detection"] and detector else None,
                                detector.weights_sha256 if pick["real_detection"] and detector else None)
    pipeline.flush(now + timedelta(seconds=9))
    pipeline._encode_queue.join()
    if not created:
        raise RuntimeError("sample event was quarantined; check ffmpeg and evidence output")
    audit.record("demo_trigger", f"{mapped} on {camera_id}: stored-sample incident")
    return created[0]
