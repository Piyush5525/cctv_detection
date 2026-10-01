"""Proves the Phase 1c follow-up 3 OCSortTracker fix (pruning + history
cap) produces IDENTICAL tracking results on a real test clip, by running
the pre-fix and post-fix tracker implementations over the same clip with
the same real YOLO person detections and diffing track_id/bbox/
confidence/velocity for every tracked person in every frame.

Usage:
    python scripts/compare_tracker_before_after.py
"""
import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import os
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')

import cv2
import numpy as np


def load_tracker_class(path: str, modname: str):
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod.OCSortTracker


def run_clip(tracker_cls, clip_path: str, max_frames: int = 150):
    from snatch_detection.tracking.detector import PersonDetector
    detector = PersonDetector(model_path='yolov8n.pt')
    tracker = tracker_cls()

    cap = cv2.VideoCapture(clip_path)
    results_log = []
    idx = 0
    while idx < max_frames:
        ret, frame = cap.read()
        if not ret:
            break
        dets = detector.detect(frame)
        tracked = tracker.update(dets, frame)
        for t in tracked:
            results_log.append((
                idx, int(t.track_id),
                tuple(np.round(t.bbox, 2).tolist()),
                round(float(t.confidence), 4),
                tuple(np.round(t.velocity, 4).tolist()),
            ))
        idx += 1
    cap.release()
    return results_log


def main():
    clip = str(Path(__file__).parent.parent / "testing" / "snatch.mp4")
    before_path = str(Path(__file__).parent.parent / "snatch_detection" / "tracking" / "_tracker_before_snapshot.py")

    if not Path(before_path).exists():
        print(f"ERROR: before-snapshot not found at {before_path} -- "
              f"run this immediately after creating it from git history", file=sys.stderr)
        sys.exit(1)

    print("Running BEFORE (pre-fix) tracker over the clip...")
    before_cls = load_tracker_class(before_path, "tracker_before_mod")
    before_results = run_clip(before_cls, clip)
    print(f"BEFORE: {len(before_results)} tracked-person entries")

    print("Running AFTER (post-fix) tracker over the clip...")
    from snatch_detection.tracking.tracker import OCSortTracker as after_cls
    after_results = run_clip(after_cls, clip)
    print(f"AFTER: {len(after_results)} tracked-person entries")

    identical = before_results == after_results
    print(f"\nIDENTICAL: {identical}")
    if not identical:
        for i, (b, a) in enumerate(zip(before_results, after_results)):
            if b != a:
                print(f"  first diff at entry {i}: before={b} after={a}")
                break
        if len(before_results) != len(after_results):
            print(f"  length mismatch: before={len(before_results)} after={len(after_results)}")


if __name__ == "__main__":
    main()
