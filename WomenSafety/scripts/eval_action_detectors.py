"""Lite evaluation of the EXPERIMENTAL action detectors on the clips already in the repo (no data collection).

PRELIMINARY, TINY SAMPLE: a handful of clips, no per-frame ground truth, no fall footage at all. The numbers
below describe these clips only; they are NOT accuracy estimates.

Runs the real ActionEngine (real YOLOv8n-pose, real CLIP) in deterministic VIDEO time (no sleeping, no wall
clock), applies the same N-of-M confirmation the live pipeline applies, and prints per clip and detector:
expected? / detected? / peak score / first-confirmation time (seconds from clip start) / false alarm.

    python scripts/eval_action_detectors.py [--max-seconds 80] [--json out.json] [clip ...]
"""
import argparse
import json
import os
import sys
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ["LIVE_CAMERA_WORKERS_ENABLED"] = "false"
os.environ["ALERTS_ENABLED"] = "false"

import cv2

from api.services.action_detectors import ACTION_NAMES, ActionEngine

# clip -> detector it is expected to trigger (None = a normal / other-hazard clip: any detection is a false alarm)
CLIPS = [
    ("data/office_fight.mp4", "violence"),
    ("scraped_data/videos/CCTV_footage_street_fight_caught_on_came_03.mp4", "violence"),
    ("testing/snatch.mp4", "snatch"),
    ("../snatch_detection_system/data/snatch.mp4", "snatch"),
    ("../snatch_detection_system/data/snatch2.mp4", "snatch"),
    ("data/crash.mp4", None),
    ("data/fire.mp4", None),
    ("scraped_data/videos/CCTV_footage_building_fire_caught_on_cam_00.mp4", None),
    ("scraped_data/videos/CCTV_footage_building_fire_caught_on_cam_04.mp4", None),
    ("scraped_data/videos/single_dashcam_car_accident_short_clip_01.mp4", None),
]


def evaluate(path: Path, max_seconds: float, names=ACTION_NAMES) -> dict:
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    stats = {n: {"peak_score": 0.0, "raw_hits": 0, "evaluated": 0, "first_confirmed_s": None, "confirmed_signals": None, "best_signals": None, "recent": None} for n in names}
    base = datetime.now(timezone.utc) - timedelta(days=1)

    def on_verdict(detector, result, frame, ts, offset):
        st = stats[detector.name]
        if st["recent"] is None:
            st["recent"] = deque(maxlen=detector.confirm_m)
        t = (ts - base).total_seconds()
        st["evaluated"] += 1
        if result.score > st["peak_score"]:
            st["peak_score"], st["best_signals"] = result.score, result.signals
        st["raw_hits"] += int(result.detected)
        st["recent"].append(result.detected)
        if st["first_confirmed_s"] is None and sum(st["recent"]) >= detector.confirm_n and result.detected:
            st["first_confirmed_s"] = round(t, 2)
            st["confirmed_signals"] = result.signals

    engine = ActionEngine("EVAL", names, on_verdict=on_verdict)
    if not engine.enabled:
        raise SystemExit("pose model unavailable")
    t0, idx, wall0 = None, 0, time.perf_counter()
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        t = idx / fps
        idx += 1
        if t > max_seconds:
            break
        engine.process(frame, t, base + timedelta(seconds=t), video_offset_s=t)
    cap.release()
    wall = time.perf_counter() - wall0
    out = {"clip": str(path.name), "video_seconds": round(min(idx / fps, max_seconds), 1), "wall_seconds": round(wall, 1),
           "pose_passes": engine.pose_passes, "pose_ms_avg": round(1000 * engine.pose_time_s / max(engine.pose_passes, 1), 1),
           "detector_runs": engine.detector_runs, "detectors": {}}
    for n, st in stats.items():
        out["detectors"][n] = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in st.items() if k != "recent"}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clips", nargs="*")
    ap.add_argument("--max-seconds", type=float, default=90.0)
    ap.add_argument("--json")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--only", help="comma list of detectors to run (default: fall,violence,snatch)")
    args = ap.parse_args()
    todo = [(c, None) for c in args.clips] if args.clips else CLIPS
    rows = []
    for rel, expected in todo:
        path = (ROOT / rel).resolve()
        if not path.exists():
            print(f"skip (missing): {rel}")
            continue
        res = evaluate(path, args.max_seconds, names=args.only.split(",") if args.only else ACTION_NAMES)
        res["expected"] = expected
        rows.append(res)
        print(f"\n{rel}  [{res['video_seconds']}s video, {res['wall_seconds']}s wall, pose {res['pose_ms_avg']} ms/pass x {res['pose_passes']}]  expected={expected}")
        for n, d in res["detectors"].items():
            detected = d["first_confirmed_s"] is not None
            verdict = "HIT" if (detected and n == expected) else "MISSED" if (not detected and n == expected) else "FALSE ALARM" if detected else "ok (no alert)"
            print(f"   {n:9s} {verdict:13s} peak_score={d['peak_score']:.2f} raw_hits={d['raw_hits']}/{d['evaluated']} first_confirmed={d['first_confirmed_s']}")
            if args.verbose and d["best_signals"]:
                print("             best candidate:", d["best_signals"])
    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
