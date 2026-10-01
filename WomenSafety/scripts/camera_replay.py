"""Test-replay path for the CCTV event-capture pipeline (CHANGELOG.md
"CCTV Incident Capture Pipeline" phase, Part 3). Reads a registered
camera's stream_source (here always a local video file, since these are
"sample": true cameras) through the SAME real detectors main.py's live
loop uses for fire/crash (fire_detection / crash_detection YOLO) --
violence/fall/snatch are NOT run here, per the fire/crash-only eval
scope (see CHANGELOG.md "Phase 1c sampling follow-up") -- and feeds
every sampled frame's verdict into EventCapturePipeline, the identical
shared event-lifecycle/evidence module main.py is wired to.

Frame sampling uses the SAME shared TimeBasedSampler as main.py's live
loop and scripts/eval_detectors.py (api/services/frame_sampler.py) --
sampling is by VIDEO TIME (frame_index / native_fps), not raw frame
count. The ring buffer (EventCapturePipeline.add_raw_frame) still sees
EVERY frame for clip quality; only detection is throttled to the
sampled subset.

Marks every incident it creates with source="test_replay" (never
"live"), and requires a real camera_id already present in
config/cameras.json -- it does not fabricate a camera or accept
arbitrary coordinates from the command line.

Usage:
    python scripts/camera_replay.py CAM-SAMPLE-001
    python scripts/camera_replay.py CAM-SAMPLE-002 --max-seconds 30
"""
import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')

sys.path.insert(0, str(Path(__file__).parent.parent))

import cv2

from api.core.config import settings
from api.core.config_dump import print_effective_config
from api.models.camera import get_camera, resolve_stream_source
from api.models.incident_v2 import SourceKind
from api.services.event_capture import EventCapturePipeline
from api.services.frame_sampler import TimeBasedSampler
from api.services import incident_service_v2 as svc


def _build_detectors():
    from fire_detection.detector import build_fire_pipeline
    from crash_detection.detector import build_crash_pipeline
    fire = build_fire_pipeline()
    crash = build_crash_pipeline()
    return fire, crash


MODELS_DIR = Path(__file__).parent.parent / "models"


def _weights_info(weights_filename: str):
    """Both fire_detection.detector.build_fire_pipeline and
    crash_detection.detector.build_crash_pipeline hardcode their model
    path internally (models/best_nano_111.pt, models/crash_best.pt) and
    don't expose it as an attribute on the returned detector -- so this
    hashes the known path directly rather than introspecting the object."""
    p = MODELS_DIR / weights_filename
    if not p.exists():
        return str(p), None
    import hashlib
    h = hashlib.sha256(p.read_bytes()).hexdigest()
    return str(p), h


def run_replay(camera_id: str, max_seconds: float = None, sample_interval_s: float = None, confidence_floor: float = None):
    sample_interval_s = sample_interval_s if sample_interval_s is not None else settings.SAMPLE_INTERVAL_S
    # Phase 1c follow-up 2, HIGH-priority finding (see CHANGELOG.md): this
    # script's own confidence floor historically defaulted to 0.5, while
    # main.py's live loop applies NO floor (settings.FIRE_CRASH_CONFIDENCE_FLOOR
    # defaults to 0.0, matching live behavior). They are DELIBERATELY left
    # different for now -- changing the live loop's floor is out of scope
    # this phase (no threshold changes). confidence_floor here defaults to
    # 0.5 (this script's historical behavior, NOT settings.FIRE_CRASH_CONFIDENCE_FLOOR)
    # unless explicitly overridden, so existing replay-based tests are
    # unaffected; pass --confidence-floor 0.0 to match live behavior exactly.
    confidence_floor = confidence_floor if confidence_floor is not None else 0.5

    cam = get_camera(camera_id)
    if cam is None:
        print(f"ERROR: {camera_id!r} is not a registered camera (config/cameras.json)", file=sys.stderr)
        sys.exit(1)

    source = resolve_stream_source(cam)
    video_path = Path(source)
    if not video_path.is_absolute():
        video_path = Path(__file__).parent.parent / source
    if not video_path.exists():
        print(f"ERROR: stream_source file not found: {video_path}", file=sys.stderr)
        sys.exit(1)

    print(f"[Replay] camera={camera_id} name={cam.name!r} source={video_path}")
    print(f"[Replay] run metadata: detectors=['fire', 'crash'] (fire/crash-only, "
          f"matching scripts/eval_detectors.py -- violence/fall/snatch NOT run), "
          f"sample_interval_s={sample_interval_s}, confidence_floor={confidence_floor} "
          f"(live loop's settings.FIRE_CRASH_CONFIDENCE_FLOOR={settings.FIRE_CRASH_CONFIDENCE_FLOOR} -- "
          f"these are DELIBERATELY different right now, see CHANGELOG.md)")
    cli_overrides = {}
    if sample_interval_s != settings.SAMPLE_INTERVAL_S:
        cli_overrides["SAMPLE_INTERVAL_S"] = sample_interval_s
    print_effective_config(cli_overrides=cli_overrides, label="camera_replay.py run")

    fire_detector, crash_detector = _build_detectors()
    fire_weights_file, fire_weights_sha = _weights_info("best_nano_111.pt")
    crash_weights_file, crash_weights_sha = _weights_info("crash_best.pt")

    incidents_created = []

    def on_incident_ready(cam_id, ev, evidence):
        incident = svc.handle_finished_event(cam_id, ev, evidence, source=SourceKind.TEST_REPLAY)
        if incident:
            incidents_created.append(incident)

    def on_quarantine(cam_id, category, reason, event_start, partial_evidence=None):
        svc.handle_encode_failure(cam_id, category, reason, event_start, partial_evidence)
        print(f"[Replay] QUARANTINED camera={cam_id} category={category} reason={reason}")

    pipeline = EventCapturePipeline(camera_id, on_incident_ready, on_quarantine)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f"ERROR: could not open {video_path}", file=sys.stderr)
        sys.exit(1)

    native_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    sampler = TimeBasedSampler(native_fps=native_fps, sample_interval_s=sample_interval_s)

    idx = 0
    start_wall = time.time()
    last_ts = None
    RESIZE_TARGET_HEIGHT = 640
    MAX_BOX_HEIGHT_FRACTION = 0.85
    VIDEO_MIN_CONFIDENCE = confidence_floor

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        video_t = sampler.video_time_of(idx)
        if max_seconds is not None and video_t > max_seconds:
            break

        ts = datetime.now(timezone.utc)
        last_ts = ts

        h, w = frame.shape[:2]
        new_w = int(RESIZE_TARGET_HEIGHT * (w / h))
        resized = cv2.resize(frame, (new_w, RESIZE_TARGET_HEIGHT))

        # Ring buffer sees EVERY frame (clip quality) regardless of the
        # detection sampling decision below.
        pipeline.add_raw_frame(resized, ts, video_offset_s=video_t)

        if not sampler.should_process(idx):
            idx += 1
            continue

        best_category = None
        best_conf = 0.0
        best_boxes = []
        best_source = None
        best_model = None
        best_weights_file = None
        best_weights_sha = None
        best_threshold = VIDEO_MIN_CONFIDENCE

        if fire_detector is not None:
            r = fire_detector.process_frame(frame)
            if r.detection and r.confidence >= VIDEO_MIN_CONFIDENCE:
                is_whole_frame = False
                for b in r.boxes:
                    try:
                        _, y1, _, y2 = b.get("box", (0, 0, 0, 0))
                        if (y2 - y1) >= RESIZE_TARGET_HEIGHT * MAX_BOX_HEIGHT_FRACTION:
                            is_whole_frame = True
                    except Exception:
                        pass
                if not is_whole_frame and r.confidence > best_conf:
                    best_category, best_conf, best_boxes = "fire", r.confidence, r.boxes
                    best_source, best_model = "yolov8-fire", "best_nano_111.pt"
                    best_weights_file, best_weights_sha = fire_weights_file, fire_weights_sha

        if crash_detector is not None:
            r = crash_detector.process_frame(frame)
            if r.detection and r.confidence >= VIDEO_MIN_CONFIDENCE and r.confidence > best_conf:
                best_category, best_conf, best_boxes = "crash", r.confidence, r.boxes
                best_source, best_model = "yolov8-crash", "crash_best.pt"
                best_weights_file, best_weights_sha = crash_weights_file, crash_weights_sha

        formatted_boxes = []
        for b in best_boxes:
            formatted_boxes.append({
                "label": b.get("class", best_category or "unknown"),
                "confidence": b.get("confidence", best_conf),
                "box": list(b.get("box", (0, 0, 0, 0))),
            })

        pipeline.feed_detection(
            frame=resized,
            ts=ts,
            category=best_category,
            confidence=best_conf,
            boxes=formatted_boxes,
            detector_source=best_source or "none",
            model_name=best_model or "none",
            threshold_applied=best_threshold,
            weights_file=best_weights_file,
            weights_sha256=best_weights_sha,
            video_offset_s=video_t,
        )
        idx += 1
        if sampler.sampled_count % 5 == 0:
            print(f"[Replay] {camera_id} sampled_frame={sampler.sampled_count} video_t={video_t:.1f}s "
                  f"best={best_category} conf={best_conf:.2f}", flush=True)

    cap.release()
    if last_ts is not None:
        pipeline.flush(last_ts)
        pipeline._encode_queue.join()  # wait for the encoder thread to finish ffmpeg encoding

    wall_elapsed = time.time() - start_wall
    print(f"[Replay] camera={camera_id} done: {idx} frames read, {sampler.sampled_count} sampled/processed, "
          f"sample_interval_s={sample_interval_s}, wall_time={wall_elapsed:.1f}s, "
          f"incidents_created={len(incidents_created)}")
    for inc in incidents_created:
        print(f"  -> {inc.incident_id} category={inc.category.value} peak_conf={inc.detection.peak_confidence:.2f} "
              f"event_start={inc.event_start.isoformat()} duration_s={inc.duration_s}")
    return incidents_created


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Replay a registered sample camera's video file through the real CCTV event-capture pipeline (fire/crash only)")
    parser.add_argument("camera_id")
    parser.add_argument("--max-seconds", type=float, default=None)
    parser.add_argument("--sample-interval-s", type=float, default=None,
                         help=f"Detection sampling interval in seconds (default: config SAMPLE_INTERVAL_S={settings.SAMPLE_INTERVAL_S})")
    parser.add_argument("--confidence-floor", type=float, default=None,
                         help="Minimum confidence to count a fire/crash detection as a hit (default: 0.5, this "
                              "script's historical behavior -- NOT the live loop's settings.FIRE_CRASH_CONFIDENCE_FLOOR, "
                              "which defaults to 0.0/no floor; pass 0.0 here to match live behavior exactly)")
    args = parser.parse_args()
    run_replay(args.camera_id, max_seconds=args.max_seconds, sample_interval_s=args.sample_interval_s,
               confidence_floor=args.confidence_floor)
