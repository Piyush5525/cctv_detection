"""Performance guard measurement: fire/crash effective fps, CPU and memory with and without the action detectors.

Runs the real CameraWorker (real fire/crash weights, real pose model, real CLIP) on looping sample videos:
  (a) fire+crash only   vs   (b) fire+crash+fall+violence+snatch,
on ONE camera and on TWO simulated cameras. fps = fire/crash sampled frames per second actually processed
(RealtimeFrameGate-paced, SAMPLE_INTERVAL_S = 0.25 s => 4 fps ceiling). Everything is isolated in a temp DB /
evidence dir with alerts disabled, so nothing is sent anywhere.

    python scripts/measure_action_perf.py [--seconds 40] [--warmup 10] [--json out.json]
"""
import argparse
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_tmp = tempfile.mkdtemp(prefix="ws-perf-")
os.environ.update(INCIDENTS_DB_PATH=os.path.join(_tmp, "incidents.db"), EVIDENCE_ROOT_V2=os.path.join(_tmp, "evidence"),
                  LIVE_CAMERA_WORKERS_ENABLED="false", ALERTS_ENABLED="false", KMP_DUPLICATE_LIB_OK="TRUE",
                  TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID="", OMNIDIM_API_KEY="", OMNIDIM_AGENT_ID="", SERPAPI_KEY="", MAPBOX_TOKEN="", DEMO_PHONE_NUMBER="")

import psutil

from api.models.camera import get_camera
from api.services import camera_workers as cw
from api.services.detector_interface import DetectorRegistry

FIVE = ["fire", "crash", "fall", "violence", "snatch"]
FC = ["fire", "crash"]
SOURCES = ["testing/snatch.mp4", "data/office_fight.mp4"]


def run_scenario(registry, lock, detectors, n_cams, seconds, warmup):
    workers = []
    for i in range(n_cams):
        cam = get_camera("CAM-SAMPLE-003").model_copy(update={"camera_id": f"CAM-PERF-{i}", "stream_source": SOURCES[i % len(SOURCES)], "detectors": detectors})
        # incidents need a registered camera: reuse the sample camera's registry entry for location only
        w = cw.CameraWorker(cam, registry, lock)
        workers.append(w)
    for w in workers:
        w.start()
    time.sleep(warmup)
    proc = psutil.Process()
    proc.cpu_percent(None)
    counts0 = [w.gate.processed_count for w in workers]
    pose0 = [w.action.pose_passes if w.action else 0 for w in workers]
    t0 = time.time()
    peak_rss = 0
    while time.time() - t0 < seconds:
        time.sleep(1.0)
        peak_rss = max(peak_rss, proc.memory_info().rss)
    elapsed = time.time() - t0
    cpu = proc.cpu_percent(None) / psutil.cpu_count()          # share of the whole machine
    out = {"detectors": detectors, "cameras": n_cams, "seconds": round(elapsed, 1),
           "fire_crash_fps_per_camera": [round((w.gate.processed_count - c0) / elapsed, 2) for w, c0 in zip(workers, counts0)],
           "action_pose_passes_per_s": [round(((w.action.pose_passes if w.action else 0) - p0) / elapsed, 2) for w, p0 in zip(workers, pose0)],
           "throttle": [w.action.throttle if w.action else None for w in workers],
           "cpu_percent_of_machine": round(cpu, 1), "peak_rss_mb": round(peak_rss / 1e6)}
    for w in workers:
        w.stop()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=40)
    ap.add_argument("--warmup", type=float, default=10)
    ap.add_argument("--json")
    args = ap.parse_args()
    registry = DetectorRegistry(confidence_floor=0.5)
    lock = threading.Lock()
    rows = []
    for n_cams in (1, 2):
        for label, det in (("fire+crash only", FC), ("all five", FIVE)):
            res = run_scenario(registry, lock, det, n_cams, args.seconds, args.warmup)
            res["label"] = label
            rows.append(res)
            print(f"{n_cams} cam | {label:16s} | fire/crash fps {res['fire_crash_fps_per_camera']} | action pose/s {res['action_pose_passes_per_s']} "
                  f"| throttle {res['throttle']} | CPU {res['cpu_percent_of_machine']}% | peak RSS {res['peak_rss_mb']} MB", flush=True)
    for n_cams in (1, 2):
        a = next(r for r in rows if r["cameras"] == n_cams and r["label"] == "fire+crash only")
        b = next(r for r in rows if r["cameras"] == n_cams and r["label"] == "all five")
        fa, fb = sum(a["fire_crash_fps_per_camera"]) / n_cams, sum(b["fire_crash_fps_per_camera"]) / n_cams
        print(f"{n_cams} cam: fire/crash fps {fa:.2f} -> {fb:.2f} ({100 * (fb - fa) / fa:+.0f}%)  [limit: no worse than -25%]")
    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
