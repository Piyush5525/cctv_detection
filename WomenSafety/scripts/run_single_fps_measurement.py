"""Runs ONE live-loop FPS measurement in THIS process and exits --
designed to be invoked as a fresh subprocess by
scripts/measure_live_loop_fps_interleaved.py, so each repeat starts
with a clean process (no model/state carryover between repeats) and
can be timed/telemetered independently.

Prints machine telemetry (RSS memory, CPU clock, CPU temp if available,
thread count, power status) every ~60s (per-minute) alongside the
RealtimeFrameGate's own FPS log lines, plus a final JSON summary line
prefixed with RESULT_JSON: for the caller to parse.

Usage (normally invoked by the interleaved runner, not by hand):
    python scripts/run_single_fps_measurement.py --clip data/crash.mp4 \
        --legacy-enabled true --detection-only true --measure-seconds 60
"""
import argparse
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

MAX_STARTUP_WAIT_S = 150
READY_MARKER = "Detection sampling: every"
FPS_LINE_RE = re.compile(r"\[RealtimeFrameGate:fire\+crash\] effective processed FPS over last ([\d.]+)s: ([\d.]+)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--clip", required=True)
    parser.add_argument("--legacy-enabled", choices=["true", "false"], required=True)
    parser.add_argument("--detection-only", choices=["true", "false"], default="false")
    parser.add_argument("--measure-seconds", type=int, required=True)
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
        if time.time() - t0 > MAX_STARTUP_WAIT_S:
            orig_print(f"[single] WARNING: readiness marker not seen after {MAX_STARTUP_WAIT_S}s -- proceeding anyway")
            break
        time.sleep(0.5)
    startup_s = time.time() - t0
    orig_print(f"[single] ready after {startup_s:.1f}s, measuring for {args.measure_seconds}s "
               f"(legacy_enabled={args.legacy_enabled}, detection_only={args.detection_only}, clip={args.clip})")
    orig_print(f"[single] power: {get_power_status()}")

    telemetry_log = []
    measure_start = time.time()
    next_telemetry = measure_start
    while time.time() - measure_start < args.measure_seconds:
        now = time.time()
        if now >= next_telemetry:
            snap = telemetry_snapshot()
            snap["elapsed_s"] = round(now - measure_start, 1)
            telemetry_log.append(snap)
            orig_print(f"[telemetry] t={snap['elapsed_s']}s rss_mb={snap['rss_mb']} "
                       f"threads={snap['num_threads']} cpu_clock={snap['cpu_clock']} cpu_temp={snap['cpu_temp']}")
            next_telemetry += args.telemetry_interval_s
        time.sleep(0.5)

    fps_values = []
    for line in output_lines:
        m = FPS_LINE_RE.search(line)
        if m:
            fps_values.append(float(m.group(2)))

    incidents_created = sum(1 for l in output_lines if "INCIDENT CREATED" in l)
    events_started = sum(1 for l in output_lines if "EVENT START" in l)

    result = {
        "clip": args.clip,
        "legacy_enabled": args.legacy_enabled == "true",
        "detection_only": args.detection_only == "true",
        "startup_s": round(startup_s, 1),
        "fps_values": fps_values,
        "incidents_created": incidents_created,
        "events_started": events_started,
        "telemetry": telemetry_log,
    }
    orig_print("RESULT_JSON:" + json.dumps(result))


if __name__ == "__main__":
    main()
