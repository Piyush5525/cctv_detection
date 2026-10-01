"""Runs uploaded photos/videos through the real detection models and turns
the result into a real Incident -- the same models main.py's live-camera
loop uses, just invoked on demand for a single upload instead of a
continuous stream.

Design note: violence (CLIP) and fire/crash (YOLO) detectors are stateless
per-frame, so a single uploaded photo gets a real verdict from them. Fall
and snatch detection are inherently temporal (they watch a tracked person
across frames to see a fall transition or a motion/pose pattern) -- a lone
photo can't honestly produce a "fall confirmed" or "snatch" verdict, so on
a single image we only report raw pose presence, and reserve the full
stateful fall/snatch pipelines for video uploads, where real frame history
exists.
"""

import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np


def _make_json_serializable(obj: Any) -> Any:
    """YOLO detection boxes come back as numpy arrays/scalars, which Pydantic
    can't serialize -- recursively convert to plain JSON-safe types before
    this ever reaches IncidentCreate. Same shape as api_client.py's helper,
    duplicated locally to avoid importing that module here (it depends on
    the detector modules that this file also builds pipelines from)."""
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, dict):
        return {k: _make_json_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_json_serializable(v) for v in obj]
    return obj
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')

MODELS_DIR = Path(__file__).parent.parent.parent

_state = {
    "clip_model": None,
    "fire_detector": "unloaded",
    "crash_detector": "unloaded",
    "pose_detector": "unloaded",
}


def _get_clip_model():
    if _state["clip_model"] is None:
        from model import Model
        _state["clip_model"] = Model(settings_path=str(MODELS_DIR / "settings.yaml"))
    return _state["clip_model"]


def _get_fire_detector():
    if _state["fire_detector"] == "unloaded":
        from fire_detection.detector import build_fire_pipeline
        _state["fire_detector"] = build_fire_pipeline()
    return _state["fire_detector"]


def _get_crash_detector():
    if _state["crash_detector"] == "unloaded":
        from crash_detection.detector import build_crash_pipeline
        _state["crash_detector"] = build_crash_pipeline()
    return _state["crash_detector"]


def _get_pose_detector():
    if _state["pose_detector"] == "unloaded":
        try:
            from ultralytics import YOLO
            _state["pose_detector"] = YOLO("yolov8n-pose.pt")
        except Exception as e:
            print(f"[DetectionService] Pose model unavailable: {e}")
            _state["pose_detector"] = None
    return _state["pose_detector"]


class DetectionOutcome:
    def __init__(self):
        self.ran: dict[str, bool] = {}
        self.results: dict[str, dict] = {}
        self.incident = None


# Real vehicle-crash frames tested localize the "Accident" box around the
# actual collision (e.g. 473x289 or 369x312 out of a 640-tall resized
# frame). A false positive found in testing (two people fighting in an
# office corridor, misread as "Accident" at 0.55 confidence) put the box at
# 700x640 -- full resize height, most of the width: the detector claiming
# almost the entire frame is itself a bad sign, not a real localized
# object. fire_detection/crash_detection both resize to a fixed height
# (RESIZE_TARGET_HEIGHT) before inference and report box coords in that
# resized space, so the same fixed threshold applies to both.
RESIZE_TARGET_HEIGHT = 640
MAX_BOX_HEIGHT_FRACTION = 0.85


def _is_near_whole_frame_box(box) -> bool:
    try:
        _, y1, _, y2 = box
        return (y2 - y1) >= RESIZE_TARGET_HEIGHT * MAX_BOX_HEIGHT_FRACTION
    except Exception:
        return False


def _resize_like_fire_crash_detector(frame_bgr: np.ndarray) -> np.ndarray:
    """Reproduces fire_detection/crash_detection's own resize_frame (resize
    to RESIZE_TARGET_HEIGHT, preserving aspect ratio) so a second model run
    on the result shares the exact coordinate space of the crash/fire boxes
    -- needed to check whether a "crash" box actually overlaps a cluster of
    people rather than a vehicle."""
    h, w = frame_bgr.shape[:2]
    new_width = int(RESIZE_TARGET_HEIGHT * (w / h))
    return cv2.resize(frame_bgr, (new_width, RESIZE_TARGET_HEIGHT))


def _box_overlap_fraction(box_a, box_b) -> float:
    """Fraction of box_a's area covered by its intersection with box_b."""
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    area_a = max(1, (ax2 - ax1) * (ay2 - ay1))
    return inter / area_a


# A real vehicle-crash box shouldn't have several people's individual pose
# boxes packed inside it -- that pattern (many people, each with most of
# their own box overlapping the "crash" box) is what a real false positive
# looked like in testing: a crowd brawl misread as "Accident" at 0.51 with
# a tightly localized (not whole-frame) box, so neither of the other two
# filters caught it. >=3 overlapping people at >=50% of their own box area
# is treated as "this is a crowd of people, not a vehicle."
CROWD_MIN_PEOPLE = 3
CROWD_MIN_OVERLAP_FRACTION = 0.5


def _looks_like_crowd_not_vehicle(crash_box, frame_bgr: np.ndarray) -> bool:
    pose_model = _get_pose_detector()
    if pose_model is None:
        return False
    try:
        resized = _resize_like_fire_crash_detector(frame_bgr)
        results = pose_model(resized, verbose=False)
        if not results or results[0].boxes is None:
            return False
        person_boxes = results[0].boxes.xyxy.cpu().numpy()
        overlapping = sum(
            1 for pbox in person_boxes
            if _box_overlap_fraction(pbox, crash_box) >= CROWD_MIN_OVERLAP_FRACTION
        )
        return overlapping >= CROWD_MIN_PEOPLE
    except Exception:
        return False


def _redetect_after_dropping_whole_frame_boxes(detection: Optional[str], confidence: float, boxes: list, target_class_name: str):
    """Drops boxes that claim almost the entire (resized) frame, then
    recomputes the detector's own verdict from what's left -- same rule the
    detector itself uses (highest-confidence box of the matching class) so
    a real, smaller, still-present box for that class is correctly kept
    instead of being thrown out along with the bogus whole-frame one."""
    kept = [b for b in boxes if not _is_near_whole_frame_box(b.get("box", (0, 0, 0, 0)))]
    if len(kept) == len(boxes):
        return detection, confidence, kept  # nothing dropped, no change
    matching = [b for b in kept if b["class"].lower() == target_class_name.lower()]
    if not matching:
        return None, 0.0, kept
    best = max(matching, key=lambda b: b["confidence"])
    return target_class_name, best["confidence"], kept


def run_models_on_frame(frame_bgr: np.ndarray) -> DetectionOutcome:
    """Runs every stateless model on a single BGR frame and returns what
    each one found, plus whether it ran at all (vs. unavailable/no weights)."""
    outcome = DetectionOutcome()

    # Violence / general scene -- CLIP, always available (public weights).
    try:
        model = _get_clip_model()
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        prediction = model.predict(image=rgb)
        outcome.ran["violence"] = True
        outcome.results["violence"] = prediction
    except Exception as e:
        outcome.ran["violence"] = False
        outcome.results["violence"] = {"error": str(e)}

    # Fire -- real dedicated YOLO weights (best_nano_111.pt) aren't available
    # anywhere (checked this repo and its GitHub releases); fall back to
    # CLIP's own scene-level "fire on a street"/"fire in office" labels,
    # which is a real model verdict, just a weaker/more general one than a
    # purpose-trained detector would give. Clearly tagged as a fallback so
    # nothing pretends to be the dedicated detector.
    fire_detector = _get_fire_detector()
    if fire_detector is None:
        clip_label = outcome.results.get("violence", {}).get("label")
        if outcome.ran.get("violence") and clip_label in ("fire on a street", "fire in office"):
            outcome.ran["fire"] = True
            outcome.results["fire"] = {
                "detection": "Fire", "confidence": outcome.results["violence"].get("confidence", 0.0),
                "boxes": [], "model": "clip-fallback",
            }
        else:
            outcome.ran["fire"] = True
            outcome.results["fire"] = {"detection": None, "confidence": 0.0, "boxes": [], "model": "clip-fallback"}
    else:
        try:
            result = fire_detector.process_frame(frame_bgr)
            detection, confidence, kept_boxes = _redetect_after_dropping_whole_frame_boxes(
                result.detection, result.confidence, result.boxes, result.detection or ""
            )
            outcome.ran["fire"] = True
            outcome.results["fire"] = {"detection": detection, "confidence": confidence, "boxes": kept_boxes, "model": "yolov8-fire"}
        except Exception as e:
            outcome.ran["fire"] = False
            outcome.results["fire"] = {"error": str(e)}

    # Crash -- same situation as fire: no dedicated crash_best.pt anywhere,
    # fall back to CLIP's "car crash" label.
    crash_detector = _get_crash_detector()
    if crash_detector is None:
        clip_label = outcome.results.get("violence", {}).get("label")
        if outcome.ran.get("violence") and clip_label == "car crash":
            outcome.ran["crash"] = True
            outcome.results["crash"] = {
                "detection": "Accident", "confidence": outcome.results["violence"].get("confidence", 0.0),
                "boxes": [], "model": "clip-fallback",
            }
        else:
            outcome.ran["crash"] = True
            outcome.results["crash"] = {"detection": None, "confidence": 0.0, "boxes": [], "model": "clip-fallback"}
    else:
        try:
            result = crash_detector.process_frame(frame_bgr)
            detection, confidence, kept_boxes = _redetect_after_dropping_whole_frame_boxes(
                result.detection, result.confidence, result.boxes, result.detection or ""
            )
            if detection and kept_boxes and _looks_like_crowd_not_vehicle(kept_boxes[0]["box"], frame_bgr):
                detection, confidence, kept_boxes = None, 0.0, []
            outcome.ran["crash"] = True
            outcome.results["crash"] = {"detection": detection, "confidence": confidence, "boxes": kept_boxes, "model": "yolov8-crash"}
        except Exception as e:
            outcome.ran["crash"] = False
            outcome.results["crash"] = {"error": str(e)}

    # Pose presence only -- NOT a fall verdict, see module docstring.
    pose_model = _get_pose_detector()
    if pose_model is None:
        outcome.ran["pose"] = False
        outcome.results["pose"] = {"error": "pose model unavailable"}
    else:
        try:
            results = pose_model(frame_bgr, verbose=False)
            person_count = len(results[0].boxes) if results and results[0].boxes is not None else 0
            outcome.ran["pose"] = True
            outcome.results["pose"] = {"person_count": person_count}
        except Exception as e:
            outcome.ran["pose"] = False
            outcome.results["pose"] = {"error": str(e)}

    outcome.ran["snatch"] = False
    outcome.results["snatch"] = {"error": "snatch detection needs a video (motion over time), not a single photo"}

    return outcome


# A still photo can't be checked for the multi-frame persistence used on
# video (see detect_video_and_create_incidents), so its fire/crash bar is
# simply raised to the same 0.5 floor that testing showed separates real
# hits (carfire.png 0.73, private-car-park 0.62, a real screenshot 0.51)
# from noise (a CCTV photo misread as "Accident" at 0.31).
IMAGE_FIRE_CRASH_MIN_CONFIDENCE = 0.5


def best_detection_from_outcome(outcome: DetectionOutcome) -> Optional[tuple[str, float, dict]]:
    """Picks the single strongest real finding across every model that ran,
    so one photo maps to at most one incident rather than five. Fire/crash
    already fold in the CLIP fallback (see run_models_on_frame), so only
    "violence" is read from CLIP directly here -- otherwise a fire/crash
    photo would double-count the same CLIP signal as two candidates."""
    candidates = []

    clip_result = outcome.results.get("violence", {})
    clip_label = clip_result.get("label")
    if outcome.ran.get("violence") and clip_label in ("fight on a street", "street violence", "violence in office"):
        candidates.append(("violence", clip_result.get("confidence", 0.0), {"model": "clip", "label": clip_label}))

    fire_result = outcome.results.get("fire", {})
    if outcome.ran.get("fire") and fire_result.get("detection") and fire_result.get("confidence", 0.0) >= IMAGE_FIRE_CRASH_MIN_CONFIDENCE:
        candidates.append(("fire", fire_result.get("confidence", 0.0), {"model": fire_result.get("model", "unknown"), "boxes": fire_result.get("boxes")}))

    crash_result = outcome.results.get("crash", {})
    if outcome.ran.get("crash") and crash_result.get("detection") and crash_result.get("confidence", 0.0) >= IMAGE_FIRE_CRASH_MIN_CONFIDENCE:
        candidates.append(("crash", crash_result.get("confidence", 0.0), {"model": crash_result.get("model", "unknown"), "boxes": crash_result.get("boxes")}))

    if not candidates:
        return None
    return max(candidates, key=lambda c: c[1])


def _extract_frames(video_path: Path, max_frames: int = 90, sample_fps: float = 6.0):
    """Samples frames from an uploaded video at a fixed rate rather than
    processing every frame -- keeps a long dashcam clip from taking minutes
    to run through five models, while still giving the stateful fall/snatch
    trackers enough consecutive frames to see real motion. Returns a list of
    (frame_bgr, timestamp_seconds)."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return []
    native_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, round(native_fps / sample_fps))

    frames = []
    idx = 0
    while len(frames) < max_frames:
        ret, frame = cap.read()
        if not ret:
            break
        if idx % step == 0:
            frames.append((frame, idx / native_fps))
        idx += 1
    cap.release()
    return frames


async def detect_video_and_create_incidents(
    video_path: Path,
    raw_video_bytes: bytes,
    camera_id: str,
    location_name: str,
    latitude: float,
    longitude: float,
    min_confidence: float = 0.3,
) -> dict:
    """Runs a real, stateful pass over a sampled sequence of frames from an
    uploaded video -- the fall and snatch detectors get genuine frame-to-frame
    history (tracking, pose-over-time, motion), the same as main.py's live
    loop, rather than being evaluated one frame at a time with no memory."""
    import time as _time
    from main import build_fall_pipeline
    from snatch_detection.detector import build_snatch_pipeline

    frames = _extract_frames(video_path)
    report = {
        "frames_sampled": len(frames),
        "models_ran": {},
        "findings": [],
        "incidents_created": [],
    }
    if not frames:
        report["note"] = "Could not read any frames from the uploaded video"
        return report

    fall_detector, fall_state_mgr = build_fall_pipeline()
    snatch_detector, _ = build_snatch_pipeline()
    report["models_ran"]["fall"] = fall_detector is not None
    report["models_ran"]["snatch"] = snatch_detector is not None

    fall_alerted_ids = set()
    fall_finding = None
    snatch_finding = None
    wall_clock = _time.time()

    # Fire/crash on video: a real event holds up across several consecutive
    # sampled frames at a real confidence level. Two failure modes showed up
    # in testing that a single "best frame" pick can't tell apart from a
    # genuine detection: a brief high-confidence misread lasting only 1-2
    # frames (e.g. a fight video misread as "Smoke" at 0.76-0.81 for one
    # 0.3s blip), and a persistently low-confidence misread of a static
    # background object across many frames (e.g. a parked scooter read as
    # "Accident" at a stable ~0.25-0.35 for 16 straight frames). Requiring
    # BOTH >=0.5 confidence AND a run of >=3 consecutive qualifying frames
    # rejects both patterns while still keeping a real, sustained event
    # (verified: a genuine crash clip holds >=0.60 across 12 consecutive
    # frames in testing).
    VIDEO_MIN_CONFIDENCE = 0.5
    VIDEO_MIN_RUN = 3
    fire_run: list = []  # consecutive (confidence, data, frame, ts) at >= threshold
    crash_run: list = []
    best_sustained: Optional[tuple] = None  # (type, confidence, data, frame, ts)

    def _extend_run(run, ok, entry):
        if ok:
            run.append(entry)
        else:
            run.clear()
        return run

    for frame_bgr, ts in frames:
        outcome = run_models_on_frame(frame_bgr)

        fire_r = outcome.results.get("fire", {})
        fire_ok = outcome.ran.get("fire") and fire_r.get("detection") and fire_r.get("confidence", 0) >= VIDEO_MIN_CONFIDENCE
        fire_run = _extend_run(fire_run, fire_ok, ("fire", fire_r.get("confidence", 0), {"model": fire_r.get("model"), "boxes": fire_r.get("boxes")}, frame_bgr, ts))
        if len(fire_run) >= VIDEO_MIN_RUN:
            candidate = max(fire_run, key=lambda e: e[1])
            if best_sustained is None or candidate[1] > best_sustained[1]:
                best_sustained = candidate

        crash_r = outcome.results.get("crash", {})
        crash_ok = outcome.ran.get("crash") and crash_r.get("detection") and crash_r.get("confidence", 0) >= VIDEO_MIN_CONFIDENCE
        crash_run = _extend_run(crash_run, crash_ok, ("crash", crash_r.get("confidence", 0), {"model": crash_r.get("model"), "boxes": crash_r.get("boxes")}, frame_bgr, ts))
        if len(crash_run) >= VIDEO_MIN_RUN:
            candidate = max(crash_run, key=lambda e: e[1])
            if best_sustained is None or candidate[1] > best_sustained[1]:
                best_sustained = candidate

        # Violence (CLIP) has no video-specific model, so it isn't subject
        # to the same false-positive pattern seen in fire/crash YOLO -- keep
        # it as a single-frame best-of, same as before.
        vio_r = outcome.results.get("violence", {})
        if outcome.ran.get("violence") and vio_r.get("label") in ("fight on a street", "street violence", "violence in office"):
            candidate = ("violence", vio_r.get("confidence", 0), {"model": "clip", "label": vio_r.get("label")}, frame_bgr, ts)
            if best_sustained is None or candidate[1] > best_sustained[1]:
                best_sustained = candidate

        if fall_detector is not None and fall_finding is None:
            try:
                persons = fall_detector.track(frame_bgr)
                states = fall_state_mgr.update(persons, wall_clock + ts, frame=frame_bgr)
                for pid, state in states.items():
                    fr = state.fall_result
                    if fr and fr.state.value == 'FALL_CONFIRMED' and pid not in fall_alerted_ids:
                        fall_finding = (0.85, {"track_id": pid, "fall_state": fr.state.value}, frame_bgr, ts)
                        fall_alerted_ids.add(pid)
            except Exception as e:
                report["models_ran"]["fall_error"] = str(e)

        if snatch_detector is not None and snatch_finding is None:
            try:
                result = snatch_detector.process_frame(frame_bgr)
                if result and result.verdict in ('ALERT', 'FLAG'):
                    snatch_finding = (result.vote, {
                        "verdict": result.verdict, "vote": result.vote,
                        "p_motion": result.p_motion, "p_pose": result.p_pose, "p_context": result.p_context,
                    }, frame_bgr, ts)
            except Exception as e:
                report["models_ran"]["snatch_error"] = str(e)

    candidates = []
    if best_sustained:
        name, conf, data, frame, ts = best_sustained
        candidates.append((name, conf, data, frame, ts))
    if fall_finding:
        conf, data, frame, ts = fall_finding
        candidates.append(("fall", conf, data, frame, ts))
    if snatch_finding:
        conf, data, frame, ts = snatch_finding
        candidates.append(("snatch", conf, data, frame, ts))

    if not candidates:
        report["note"] = "No detector produced a finding above threshold across sampled frames"
        return report

    detection_type, confidence, detection_data, frame_bgr, ts = max(candidates, key=lambda c: c[1])
    report["findings"] = [{"type": c[0], "confidence": c[1], "timestamp_in_video": c[4]} for c in candidates]

    if confidence < min_confidence:
        report["note"] = f"Best finding ({detection_type}, {confidence:.2f}) below threshold {min_confidence}"
        return report

    incident = _create_test_replay_incident(detection_type, confidence, detection_data, frame_bgr, camera_id)
    if incident is None:
        report["note"] = "Detection crossed threshold but could not be turned into a valid test_replay incident (see server log)"
        return report
    report["incidents_created"].append(incident.to_dict())
    return report


async def detect_and_create_incident(
    frame_bgr: np.ndarray,
    camera_id: str,
    location_name: str,
    latitude: float,
    longitude: float,
    raw_video_bytes: Optional[bytes] = None,
    min_confidence: float = 0.3,
) -> dict:
    """The actual end-to-end path: run every real model on the given frame,
    pick the strongest finding, save evidence, and create a real Incident --
    the same downstream path (dashboard, map, WebSocket push) a live camera
    detection already uses. Returns a report of what ran either way, even
    when nothing crossed the confidence threshold, so the caller can show
    an honest "no detection" result rather than silence."""
    outcome = run_models_on_frame(frame_bgr)
    best = best_detection_from_outcome(outcome)

    report = {
        "models_ran": outcome.ran,
        "model_results": outcome.results,
        "incident_created": False,
        "incident": None,
    }

    if best is None:
        return report

    detection_type, confidence, detection_data = best
    if confidence < min_confidence:
        report["note"] = f"Best finding ({detection_type}, {confidence:.2f}) below threshold {min_confidence}"
        return report

    incident = _create_test_replay_incident(detection_type, confidence, detection_data, frame_bgr, camera_id)
    if incident is None:
        report["note"] = "Detection crossed threshold but could not be turned into a valid test_replay incident (see server log)"
        return report

    report["incident_created"] = True
    report["incident"] = incident.to_dict()
    return report


def _create_test_replay_incident(detection_type: str, confidence: float, detection_data: dict,
                                  frame_bgr: np.ndarray, camera_id: str):
    """Turns a single detect.py upload's finding into a real CCTV-schema
    Incident (api/models/incident_v2.py), marked source="test_replay" --
    this dev/test endpoint requires a registered camera_id (enforced in
    api/routes/detect.py) and takes its location from the camera
    registry, never from the request. Reuses the SAME SQLite-backed
    incident_service_v2 the live loop and camera_replay.py write to, so
    there is exactly one incident store for the whole product, not two
    divergent ones."""
    from api.services import incident_service_v2 as svc_v2
    from api.services.event_capture import ActiveEvent, FrameSample, EVIDENCE_ROOT, THUMBNAIL_WIDTH, ffmpeg_available, _sha256_file
    from api.models.incident_v2 import SourceKind
    import cv2 as _cv2
    from pathlib import Path as _Path
    from datetime import timezone as _timezone

    now = datetime.now(_timezone.utc)
    boxes = detection_data.get("boxes", []) if isinstance(detection_data, dict) else []
    formatted_boxes = [
        {"label": b.get("class", detection_type), "confidence": b.get("confidence", confidence), "box": list(b.get("box", (0, 0, 0, 0)))}
        for b in boxes
    ] if boxes else [{"label": detection_type, "confidence": confidence, "box": [0, 0, 0, 0]}]

    if not ffmpeg_available():
        print("[DetectionService] ffmpeg not available -- cannot build test_replay incident evidence")
        return None

    incident_id = f"{detection_type}_{uuid.uuid4().hex[:10]}"
    day_dir = EVIDENCE_ROOT / camera_id / now.strftime("%Y-%m-%d") / incident_id
    day_dir.mkdir(parents=True, exist_ok=True)

    best_frame_path = day_dir / "best_frame.jpg"
    _cv2.imwrite(str(best_frame_path), frame_bgr)
    annotated_path = day_dir / "annotated_frame.jpg"
    _cv2.imwrite(str(annotated_path), frame_bgr)
    h, w = frame_bgr.shape[:2]
    thumb_h = max(1, int(h * (THUMBNAIL_WIDTH / w)))
    thumb = _cv2.resize(frame_bgr, (THUMBNAIL_WIDTH, thumb_h))
    thumb_path = day_dir / "thumbnail.jpg"
    _cv2.imwrite(str(thumb_path), thumb)

    # A single uploaded photo has no clip to cut -- write a 1-frame video
    # so evidence.clip_path/sha256_clip are honestly "a real 1-frame clip
    # of the uploaded photo", not a fabricated multi-frame clip.
    import subprocess
    raw_clip = day_dir / "_raw.mp4"
    out = _cv2.VideoWriter(str(raw_clip), _cv2.VideoWriter_fourcc(*"mp4v"), 1.0, (w, h))
    out.write(frame_bgr)
    out.release()
    clip_path = day_dir / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw_clip),
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(clip_path)],
        check=True, capture_output=True,
    )
    raw_clip.unlink(missing_ok=True)

    fake_event = ActiveEvent(
        category=detection_type,
        event_start=now,
        last_detection_at=now,
        frames=[FrameSample.from_ndarray(frame_bgr, now, confidence, formatted_boxes)],
        confirmations="1 of 1",
        detector_source="upload-single-frame",
        model_name="detection_service.run_models_on_frame",
        threshold_applied=0.3,
    )
    evidence_raw = {
        "incident_id": incident_id,
        "best_frame_path": str(best_frame_path),
        "annotated_frame_path": str(annotated_path),
        "thumbnail_path": str(thumb_path),
        "clip_path": str(clip_path),
        "clip_duration_s": 1.0,
        "width": w, "height": h, "fps": 1.0,
        "sha256_clip": _sha256_file(clip_path),
        "sha256_frame": _sha256_file(best_frame_path),
        "best": fake_event.frames[0],
        "hit_frames": fake_event.frames,
    }
    return svc_v2.handle_finished_event(camera_id, fake_event, evidence_raw, source=SourceKind.TEST_REPLAY)
