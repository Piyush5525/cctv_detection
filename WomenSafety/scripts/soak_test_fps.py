"""20-minute soak test (Phase 1c follow-up 2 item 3): runs ONE condition
(legacy ON by default) continuously in a SINGLE process for a long
duration, logging FPS and memory (RSS) over time every minute, to
distinguish:
  - FPS falls, memory grows -> possible leak (accumulating objects
    driving GC/allocator pressure, which can itself slow down a
    Python process over time).
  - FPS falls, memory STABLE -> likely thermal/CPU throttling (the
    process's own footprint isn't growing, so something external to
    this process's memory use is slowing it down).
  - Neither falls -> no drift, the earlier blocked-order measurement's
    apparent decline was something else (e.g. genuinely order-related,
    which the interleaved measurement should also reveal).

Usage:
    python scripts/soak_test_fps.py --clip data/crash.mp4 --duration-s 1200
"""
import argparse
import os
import re
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

READY_MARKER = "Detection sampling: every"
FPS_LINE_RE = re.compile(r"\[RealtimeFrameGate:fire\+crash\] effective processed FPS over last ([\d.]+)s: ([\d.]+)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--clip", default=str(Path(__file__).parent.parent / "data" / "crash.mp4"))
    parser.add_argument("--duration-s", type=int, default=1200)  # 20 minutes
    parser.add_argument("--legacy-enabled", choices=["true", "false"], default="true")
    parser.add_argument("--detection-only", choices=["true", "false"], default="true")
    parser.add_argument("--telemetry-interval-s", type=int, default=60)
    args = parser.parse_args()

    os.environ["CAMERA_SOURCE"] = args.clip
    os.environ["CAMERA_ROTATE"] = "0"
    os.environ["API_ENABLED"] = "0"
    os.environ["ALERTS_ENABLED"] = "false"
    os.environ["CAMERA_ID"] = "CAM-SAMPLE-001"
    os.environ["LEGACY_DETECTORS_ENABLED"] = args.legacy_enabled
    os.environ["DETECTION_ONLY_MODE"] = args.detection_only
    os.environ["VIOLENCE_DETECTION"] = "1"
    os.environ["FALL_DETECTION"] = "1"
    os.environ["SNATCH_DETECTION"] = "1"
    os.environ["FIRE_DETECTION"] = "1"
    os.environ["CRASH_DETECTION"] = "1"

    import main as main_module
    from scripts.system_telemetry import telemetry_snapshot, get_power_status

    output_lines = []
    orig_print = print

    def _capturing_print(*a, **kw):
        msg = " ".join(str(x) for x in a)
        output_lines.append(msg)
        orig_print(*a, **kw)
        sys.stdout.flush()

    import builtins
    builtins.print = _capturing_print

    t = threading.Thread(target=lambda: main_module.main(headless=True), daemon=True)
    t.start()

    t0 = time.time()
    while not any(READY_MARKER in line for line in output_lines):
        if time.time() - t0 > 150:
            break
        time.sleep(0.5)
    orig_print(f"[soak] ready after {time.time()-t0:.1f}s, running for {args.duration_s}s "
               f"(legacy_enabled={args.legacy_enabled}, detection_only={args.detection_only})")
    orig_print(f"[soak] power: {get_power_status()}")

    start = time.time()
    next_telemetry = start
    rss_series = []
    while time.time() - start < args.duration_s:
        now = time.time()
        if now >= next_telemetry:
            snap = telemetry_snapshot()
            elapsed = round(now - start, 1)
            rss_series.append((elapsed, snap["rss_mb"]))
            # FPS seen so far in this telemetry window
            recent_fps = [float(m.group(2)) for line in output_lines[-50:] if (m := FPS_LINE_RE.search(line))]
            orig_print(f"[soak] t={elapsed}s rss_mb={snap['rss_mb']} threads={snap['num_threads']} "
                       f"cpu_clock={snap['cpu_clock']} cpu_temp={snap['cpu_temp']} "
                       f"recent_fps_samples={recent_fps[-3:] if recent_fps else []}")
            next_telemetry += args.telemetry_interval_s
        time.sleep(1)

    all_fps = [float(m.group(2)) for line in output_lines if (m := FPS_LINE_RE.search(line))]
    orig_print(f"\n[soak] DONE. Total FPS samples: {len(all_fps)}")
    orig_print(f"[soak] FPS over time (all samples): {all_fps}")
    orig_print(f"[soak] RSS over time (elapsed_s, rss_mb): {rss_series}")
    if len(rss_series) >= 2:
        growth = rss_series[-1][1] - rss_series[0][1]
        orig_print(f"[soak] RSS growth over {rss_series[-1][0]:.0f}s: {growth:+.1f} MB "
                   f"({growth / (rss_series[-1][0] / 60):.1f} MB/min average)")
    if len(all_fps) >= 2:
        first_half = all_fps[:len(all_fps)//2]
        second_half = all_fps[len(all_fps)//2:]
        orig_print(f"[soak] FPS first half mean: {sum(first_half)/len(first_half):.2f}, "
                   f"second half mean: {sum(second_half)/len(second_half):.2f}")


if __name__ == "__main__":
    main()
