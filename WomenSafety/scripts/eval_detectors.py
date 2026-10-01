"""Eval harness for the DetectorRegistry (Phase 1c hardening item 7,
extended by the Phase 1c sampling follow-up). Takes a manifest of
{video/image path: expected_class} and reports each as a hit, a miss,
or "not supported" -- a class no registered detector can ever report is
NEVER counted as a miss, since penalizing a detector for not covering a
class it was never built to cover would be meaningless. Only fire and
crash are registered (see detector_interface.py) -- any manifest entry
for "snatching", "fall", "violence", etc. is correctly reported as
not_supported here, not as a miss.

Frame sampling uses the SAME shared rule as main.py's live loop and
scripts/camera_replay.py (api/services/frame_sampler.py), by VIDEO
TIME, not frame count:
  --fast (default): TimeBasedSampler, deterministic, samples by the
    video file's own timeline (frame_index / native_fps). Reproducible
    regardless of how fast this machine can run inference -- every run
    against the same clip samples the exact same frames.
  --realtime: RealtimeFrameGate, samples against the actual wall clock
    as frames are read, and reports the ACTUALLY ACHIEVED effective_fps
    (which can be lower than the target 1/sample_interval_s if
    inference itself is slower than the interval) -- this simulates
    what the live loop experiences, rather than assuming inference
    always keeps up.

Every run's metadata (mode, sample_interval_s, and effective FPS)
is printed alongside the metrics, per instruction: run metadata is
not separable from the results it produced.

Usage:
    python scripts/eval_detectors.py manifest.json
    python scripts/eval_detectors.py manifest.json --realtime
    python scripts/eval_detectors.py manifest.json --sample-interval-s 0.5
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import os
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')

import cv2

from api.core.config import settings
from api.core.config_dump import print_effective_config
from api.services.detector_interface import DetectorRegistry
from api.services.frame_sampler import TimeBasedSampler, RealtimeFrameGate


def eval_one(registry: DetectorRegistry, path: str, expected_class: str,
             sample_interval_s: float, realtime: bool) -> dict:
    if not registry.supports_class(expected_class):
        return {"path": path, "expected_class": expected_class, "result": "not_supported",
                "note": f"no registered detector covers class {expected_class!r} "
                        f"(registered classes: {sorted(registry.all_supported_classes())})"}

    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return {"path": path, "expected_class": expected_class, "result": "error", "note": "could not open file"}

    native_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    if realtime:
        gate = RealtimeFrameGate(sample_interval_s=sample_interval_s, label=f"eval:{Path(path).name}")
    else:
        sampler = TimeBasedSampler(native_fps=native_fps, sample_interval_s=sample_interval_s)

    hit = False
    best_conf = 0.0
    idx = 0
    wall_start = time.time()
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        should_process = gate.should_process() if realtime else sampler.should_process(idx)
        if should_process:
            for detector in registry.all():
                if expected_class not in detector.classes:
                    continue
                r = detector.detect(frame)
                if r.detection and r.confidence >= detector.threshold:
                    hit = True
                    best_conf = max(best_conf, r.confidence)
        idx += 1
    cap.release()
    wall_elapsed = time.time() - wall_start

    frames_checked = gate.processed_count if realtime else sampler.sampled_count
    if realtime:
        # Final update in case the clip ended before a 5s logging window
        # rolled over -- report the real achieved rate over the whole run.
        effective_fps = frames_checked / wall_elapsed if wall_elapsed > 0 else 0.0
    else:
        effective_fps = sampler.effective_sampled_fps

    return {
        "path": path, "expected_class": expected_class,
        "result": "hit" if hit else "miss",
        "best_confidence": round(best_conf, 4) if hit else None,
        "frames_checked": frames_checked,
        "mode": "realtime" if realtime else "fast",
        "sample_interval_s": sample_interval_s,
        "effective_fps": round(effective_fps, 2),
    }


def main():
    parser = argparse.ArgumentParser(description="Eval harness for the fire/crash DetectorRegistry")
    parser.add_argument("manifest", help="JSON manifest: [{\"path\":..., \"expected_class\":...}, ...]")
    parser.add_argument("--realtime", action="store_true",
                         help="Sample against the real wall clock (like the live loop) instead of deterministic video-time sampling")
    parser.add_argument("--sample-interval-s", type=float, default=None,
                         help=f"Override the sampling interval (default: config SAMPLE_INTERVAL_S={settings.SAMPLE_INTERVAL_S})")
    parser.add_argument("--confidence-floor", type=float, default=0.5,
                         help="Minimum confidence to count a fire/crash detection as a hit (default: 0.5, this "
                              "harness's historical behavior -- NOT the live loop's settings.FIRE_CRASH_CONFIDENCE_FLOOR, "
                              "which defaults to 0.0/no floor; pass the same value as the live loop to compare "
                              "apples-to-apples, see CHANGELOG.md's HIGH-priority finding on this)")
    args = parser.parse_args()

    sample_interval_s = args.sample_interval_s if args.sample_interval_s is not None else settings.SAMPLE_INTERVAL_S

    manifest = json.loads(Path(args.manifest).read_text())
    registry = DetectorRegistry(confidence_floor=args.confidence_floor)
    print(f"Registered detectors: {[d.name for d in registry.all()]} (fire/crash only -- "
          f"violence/fall/snatch are NOT run by this harness, see main.py's LEGACY_DETECTORS_ENABLED "
          f"for how the live loop's fire/crash-only throughput compares)")
    print(f"Supported classes: {sorted(registry.all_supported_classes())}")
    print(f"Run metadata: mode={'realtime' if args.realtime else 'fast'}, sample_interval_s={sample_interval_s}, "
          f"confidence_floor={args.confidence_floor} (live loop's settings.FIRE_CRASH_CONFIDENCE_FLOOR="
          f"{settings.FIRE_CRASH_CONFIDENCE_FLOOR} -- DELIBERATELY different right now, see CHANGELOG.md)")
    cli_overrides = {"SAMPLE_INTERVAL_S": sample_interval_s} if args.sample_interval_s is not None else {}
    print_effective_config(cli_overrides=cli_overrides, label="eval_detectors.py run")
    print()

    results = [eval_one(registry, entry["path"], entry["expected_class"], sample_interval_s, args.realtime)
               for entry in manifest]

    for r in results:
        extra = f"  fps={r['effective_fps']}" if "effective_fps" in r else ""
        print(f"{r['result'].upper():15s} {r['path']:40s} expected={r['expected_class']!r}  {r.get('note', '')}{extra}")

    counts = {}
    for r in results:
        counts[r["result"]] = counts.get(r["result"], 0) + 1
    print(f"\nSummary: {counts}")
    print(f"Run metadata (repeated): mode={'realtime' if args.realtime else 'fast'}, sample_interval_s={sample_interval_s}")


if __name__ == "__main__":
    main()
