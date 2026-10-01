"""Measures main.py's live loop effective fire/crash-detection FPS with
the legacy violence/fall/snatch detectors ON versus OFF (Phase 1c
sampling follow-ups). Runs main.main(headless=True) against a real
video file for a fixed duration, repeated N times per condition,
toggling LEGACY_DETECTORS_ENABLED via the environment, and captures the
RealtimeFrameGate's periodic "effective processed FPS" log lines.

Usage:
    python scripts/measure_live_loop_fps.py                       # crash.mp4 (has events/encoding)
    python scripts/measure_live_loop_fps.py --clip testing/snatch.mp4 --repeats 3  # zero-event clip
"""
import argparse
import contextlib
import io
import os
import re
import statistics
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

MAX_STARTUP_WAIT_S = 150  # model loading (CLIP + fall pose + fire/crash YOLO, + a one-time resnet18 download) can legitimately take a while
DEFAULT_MEASURE_SECONDS = 30

FPS_LINE_RE = re.compile(r"\[RealtimeFrameGate:fire\+crash\] effective processed FPS over last ([\d.]+)s: ([\d.]+)")
READY_MARKER = "Detection sampling: every"


class TeeStream(io.StringIO):
    """Captures everything written to it (for later regex extraction)
    AND echoes it live to the real stdout, so progress is visible while
    the run is in flight instead of only after it completes."""
    def __init__(self, real_stdout):
        super().__init__()
        self._real_stdout = real_stdout

    def write(self, s):
        self._real_stdout.write(s)
        self._real_stdout.flush()
        return super().write(s)


def run_once(clip: str, legacy_enabled: bool, measure_seconds: int, detection_only: bool = False) -> dict:
    os.environ["CAMERA_SOURCE"] = clip
    os.environ["CAMERA_ROTATE"] = "0"
    os.environ["API_ENABLED"] = "0"  # no dashboard push needed for this measurement
    os.environ["ALERTS_ENABLED"] = "false"
    os.environ["CAMERA_ID"] = "CAM-SAMPLE-001"  # registered camera, so event_pipeline is built
    os.environ["LEGACY_DETECTORS_ENABLED"] = "true" if legacy_enabled else "false"
    os.environ["DETECTION_ONLY_MODE"] = "true" if detection_only else "false"
    # This repo's .env sets VIOLENCE_DETECTION=0/FALL_DETECTION=0/
    # SNATCH_DETECTION=0 (left over from unrelated prior testing) -- that
    # would silently make "legacy_enabled=True" a no-op. Force these to 1
    # explicitly so legacy_enabled actually controls whether
    # violence/fall/snatch run, giving a real apples-to-apples comparison.
    os.environ["VIOLENCE_DETECTION"] = "1"
    os.environ["FALL_DETECTION"] = "1"
    os.environ["SNATCH_DETECTION"] = "1"
    os.environ["FIRE_DETECTION"] = "1"
    os.environ["CRASH_DETECTION"] = "1"

    # Reload config + main fresh so LEGACY_DETECTORS_ENABLED (read at
    # import/settings-construction time) picks up the new env var.
    for mod_name in list(sys.modules):
        if mod_name in ("api.core.config", "main"):
            del sys.modules[mod_name]
    import main as main_module

    real_stdout = sys.stdout
    captured = TeeStream(real_stdout)

    def _runner():
        with contextlib.redirect_stdout(captured):
            try:
                main_module.main(headless=True)
            except Exception as e:
                print(f"main() raised: {e}")

    t = threading.Thread(target=_runner, daemon=True)
    t.start()

    t0 = time.time()
    while READY_MARKER not in captured.getvalue():
        if time.time() - t0 > MAX_STARTUP_WAIT_S:
            print(f"[measure] WARNING: readiness marker not seen after {MAX_STARTUP_WAIT_S}s -- proceeding anyway")
            break
        time.sleep(1)
    startup_s = time.time() - t0
    print(f"[measure] loop ready after {startup_s:.1f}s startup, measuring for {measure_seconds}s...")

    time.sleep(measure_seconds)

    output = captured.getvalue()
    fps_lines = FPS_LINE_RE.findall(output)
    fps_values = [float(v) for _, v in fps_lines]
    incidents_created = output.count("INCIDENT CREATED")
    events_started = output.count("EVENT START")

    return {
        "legacy_enabled": legacy_enabled,
        "startup_s": round(startup_s, 1),
        "fps_values": fps_values,
        "incidents_created": incidents_created,
        "events_started": events_started,
    }


def repeat_condition(clip: str, legacy_enabled: bool, repeats: int, measure_seconds: int, detection_only: bool = False) -> dict:
    all_fps = []
    all_incidents = 0
    all_events = 0
    for i in range(repeats):
        label = "ON" if legacy_enabled else "OFF"
        print(f"\n--- Legacy {label}, repeat {i+1}/{repeats}{' (DETECTION_ONLY_MODE)' if detection_only else ''} ---")
        r = run_once(clip, legacy_enabled, measure_seconds, detection_only=detection_only)
        all_fps.extend(r["fps_values"])
        all_incidents += r["incidents_created"]
        all_events += r["events_started"]
        print(f"[measure] repeat {i+1} fps_values: {r['fps_values']}, "
              f"events_started={r['events_started']}, incidents_created={r['incidents_created']}")

    return {
        "legacy_enabled": legacy_enabled,
        "all_fps": all_fps,
        "mean_fps": round(statistics.mean(all_fps), 2) if all_fps else None,
        "min_fps": round(min(all_fps), 2) if all_fps else None,
        "max_fps": round(max(all_fps), 2) if all_fps else None,
        "total_events_started": all_events,
        "total_incidents_created": all_incidents,
    }


def main():
    parser = argparse.ArgumentParser(description="Measure live-loop effective FPS, legacy detectors ON vs OFF")
    parser.add_argument("--clip", default=str(Path(__file__).parent.parent / "data" / "crash.mp4"))
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--measure-seconds", type=int, default=DEFAULT_MEASURE_SECONDS)
    parser.add_argument("--detection-only", action="store_true",
                         help="Set DETECTION_ONLY_MODE=true: detection+sampling run normally, but no "
                              "events/incidents/ffmpeg-encoding occur -- isolates detection throughput "
                              "from event-lifecycle+encode cost.")
    args = parser.parse_args()

    mode_note = " [DETECTION-ONLY MODE: measures detection throughput ONLY, no events/encoding]" if args.detection_only else ""
    print(f"Measuring main.py live-loop effective fire+crash FPS on {args.clip} "
          f"({args.repeats} repeat(s) per condition, {args.measure_seconds}s each){mode_note}...")

    result_on = repeat_condition(args.clip, True, args.repeats, args.measure_seconds, detection_only=args.detection_only)
    result_off = repeat_condition(args.clip, False, args.repeats, args.measure_seconds, detection_only=args.detection_only)

    print(f"\n=== Summary{mode_note} ===")
    print(f"Legacy ON:  mean={result_on['mean_fps']} min={result_on['min_fps']} max={result_on['max_fps']} fps "
          f"| events_started={result_on['total_events_started']} incidents_created={result_on['total_incidents_created']}")
    print(f"Legacy OFF: mean={result_off['mean_fps']} min={result_off['min_fps']} max={result_off['max_fps']} fps "
          f"| events_started={result_off['total_events_started']} incidents_created={result_off['total_incidents_created']}")

    if result_on["mean_fps"] and result_off["mean_fps"]:
        delta_pct = (result_off["mean_fps"] / result_on["mean_fps"] - 1) * 100
        print(f"Difference (mean): {delta_pct:+.1f}% (positive = OFF is faster)")
    else:
        print("Could not compute comparison -- insufficient FPS log lines captured.")


if __name__ == "__main__":
    main()
