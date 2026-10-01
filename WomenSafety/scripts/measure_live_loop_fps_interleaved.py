"""Interleaved, fresh-process FPS measurement (Phase 1c follow-up 2,
responding to the confound found in the earlier blocked-order
measurement: ON x3 then OFF x3 showed a monotonic FPS decline WITHIN
each condition, consistent with thermal/load drift over the ~15-20min
run, not a real ON-vs-OFF effect, since time and condition were
confounded).

Runs ON, OFF, ON, OFF, ON, OFF (order alternated, not blocked), each
repeat in a FRESH OS subprocess (python scripts/run_single_fps_measurement.py),
with a cooldown between runs to let the machine settle. Collects each
run's FPS values + telemetry (RSS, thread count, CPU clock/temp) and
reports mean/min/max per condition plus whether the interleaved data
actually supports a clean difference (now that order can't explain it).

Usage:
    python scripts/measure_live_loop_fps_interleaved.py --clip data/crash.mp4 \
        --repeats 3 --measure-seconds 60 --cooldown-s 60 --detection-only
"""
import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent


def run_subprocess(clip: str, legacy_enabled: bool, measure_seconds: int, detection_only: bool) -> dict:
    cmd = [
        sys.executable, str(SCRIPT_DIR / "run_single_fps_measurement.py"),
        "--clip", clip,
        "--legacy-enabled", "true" if legacy_enabled else "false",
        "--detection-only", "true" if detection_only else "false",
        "--measure-seconds", str(measure_seconds),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=measure_seconds + 180)
    print(proc.stdout)
    if proc.returncode != 0:
        print(f"[interleaved] subprocess exited {proc.returncode}, stderr tail:\n{proc.stderr[-1500:]}")
    for line in proc.stdout.splitlines():
        if line.startswith("RESULT_JSON:"):
            return json.loads(line[len("RESULT_JSON:"):])
    return {"fps_values": [], "telemetry": [], "incidents_created": 0, "events_started": 0}


def main():
    parser = argparse.ArgumentParser(description="Interleaved, fresh-process ON/OFF FPS measurement")
    parser.add_argument("--clip", default=str(Path(__file__).parent.parent / "data" / "crash.mp4"))
    parser.add_argument("--repeats", type=int, default=3, help="repeats PER condition (total runs = 2*repeats)")
    parser.add_argument("--measure-seconds", type=int, default=60)
    parser.add_argument("--cooldown-s", type=int, default=60)
    parser.add_argument("--detection-only", action="store_true")
    args = parser.parse_args()

    # Interleaved order: ON, OFF, ON, OFF, ... -- alternating every run,
    # not blocked, so any machine-state drift over the full run affects
    # both conditions roughly equally instead of all falling on one side.
    order = []
    for i in range(args.repeats):
        order.append(True)
        order.append(False)

    print(f"Interleaved order: {['ON' if x else 'OFF' for x in order]}")
    print(f"clip={args.clip}, measure_seconds={args.measure_seconds}, cooldown_s={args.cooldown_s}, "
          f"detection_only={args.detection_only}\n")

    results = {"ON": [], "OFF": []}
    for i, legacy_enabled in enumerate(order):
        label = "ON" if legacy_enabled else "OFF"
        print(f"\n=== Run {i+1}/{len(order)}: Legacy {label} (fresh process) ===")
        r = run_subprocess(args.clip, legacy_enabled, args.measure_seconds, args.detection_only)
        results[label].append(r)
        print(f"[interleaved] run {i+1} fps_values={r['fps_values']}, "
              f"events_started={r['events_started']}, incidents_created={r['incidents_created']}")
        if i < len(order) - 1:
            print(f"[interleaved] cooldown {args.cooldown_s}s...")
            time.sleep(args.cooldown_s)

    def summarize(label):
        all_fps = [v for r in results[label] for v in r["fps_values"]]
        all_rss = [t["rss_mb"] for r in results[label] for t in r["telemetry"]]
        return {
            "mean_fps": round(statistics.mean(all_fps), 2) if all_fps else None,
            "min_fps": round(min(all_fps), 2) if all_fps else None,
            "max_fps": round(max(all_fps), 2) if all_fps else None,
            "mean_rss_mb": round(statistics.mean(all_rss), 1) if all_rss else None,
            "run_means": [round(statistics.mean(r["fps_values"]), 2) if r["fps_values"] else None for r in results[label]],
        }

    on_summary = summarize("ON")
    off_summary = summarize("OFF")

    print("\n=== Interleaved Summary ===")
    print(f"Legacy ON:  mean={on_summary['mean_fps']} min={on_summary['min_fps']} max={on_summary['max_fps']} fps "
          f"| per-run means: {on_summary['run_means']} | mean RSS: {on_summary['mean_rss_mb']} MB")
    print(f"Legacy OFF: mean={off_summary['mean_fps']} min={off_summary['min_fps']} max={off_summary['max_fps']} fps "
          f"| per-run means: {off_summary['run_means']} | mean RSS: {off_summary['mean_rss_mb']} MB")

    if on_summary["mean_fps"] and off_summary["mean_fps"]:
        delta_pct = (off_summary["mean_fps"] / on_summary["mean_fps"] - 1) * 100
        print(f"Difference (mean): {delta_pct:+.1f}% (positive = OFF is faster)")
    else:
        print("Could not compute comparison -- insufficient FPS log lines captured.")

    # Check for a within-condition monotonic trend across runs (the
    # confound signature found in the earlier blocked-order measurement).
    on_means = [m for m in on_summary["run_means"] if m is not None]
    off_means = [m for m in off_summary["run_means"] if m is not None]
    print(f"\nON per-run means over time: {on_means}")
    print(f"OFF per-run means over time: {off_means}")
    print("(If these drift monotonically downward across the run regardless of ON/OFF, "
          "that's machine-state drift, not a condition effect -- compare against the interleaved order above.)")


if __name__ == "__main__":
    main()
