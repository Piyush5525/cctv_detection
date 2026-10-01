"""10-minute concurrent SQLite stress test (Phase 1c hardening item 5).
Runs three kinds of load against the SAME incidents.db simultaneously
for 10 minutes, all against the LIVE running API (not direct db.py
calls), to prove no "database is locked" error occurs under real
concurrent access:
  1. A writer thread hammering incident creation (direct db.py calls,
     simulating what a detection thread does).
  2. A reader thread hammering GET /api/v1/incidents and /map/groups.
  3. A patcher thread hammering PATCH .../status on existing incidents.

Usage:
    python scripts/sqlite_concurrency_test.py --duration-seconds 600
"""
import argparse
import random
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import requests

from api import db
from api.models.incident_v2 import (
    Incident, Detection, Evidence, BBox, Category, SourceKind,
)

BASE = "http://localhost:8000/api/v1"

errors_lock = threading.Lock()
errors = []
counters_lock = threading.Lock()
counters = {"writes": 0, "reads": 0, "patches": 0}


def log_error(label, e):
    with errors_lock:
        errors.append(f"{label}: {type(e).__name__}: {e}")


def writer_loop(stop_at: float):
    db.init_db()
    while time.time() < stop_at:
        try:
            now = datetime.now(timezone.utc)
            incident_id = str(uuid.uuid4())
            inc = Incident(
                incident_id=incident_id,
                camera_id="CAM-SAMPLE-001",
                camera_name="stress-test",
                place_text="stress-test",
                latitude=26.9124,
                longitude=75.7873,
                category=Category.OTHER,
                event_start=now,
                event_end=now,
                duration_s=0.1,
                detection=Detection(
                    detector_source="stress-test", model_name="stress-test",
                    peak_confidence=0.9, mean_confidence=0.9, threshold_applied=0.5,
                    frames_confirmed="3 of 5", best_frame_bbox=[],
                ),
                evidence=Evidence(
                    best_frame_path="x", thumbnail_path="y", width=1, height=1,
                    fps=1.0, sha256_frame="z",
                ),
                source=SourceKind.TEST_REPLAY,
            )
            db.insert_incident(inc.incident_id, inc.camera_id, inc.category.value,
                                inc.status.value, inc.source.value, inc.event_start.isoformat(),
                                inc.to_dict())
            with counters_lock:
                counters["writes"] += 1
        except Exception as e:
            log_error("writer", e)
        time.sleep(0.05)


def reader_loop(stop_at: float):
    while time.time() < stop_at:
        try:
            r1 = requests.get(f"{BASE}/incidents", params={"limit": 50}, timeout=10)
            r1.raise_for_status()
            r2 = requests.get(f"{BASE}/map/groups", timeout=10)
            r2.raise_for_status()
            with counters_lock:
                counters["reads"] += 1
        except Exception as e:
            log_error("reader", e)
        time.sleep(0.1)


def patcher_loop(stop_at: float):
    while time.time() < stop_at:
        try:
            r = requests.get(f"{BASE}/incidents", params={"limit": 20}, timeout=10)
            r.raise_for_status()
            incidents = r.json().get("incidents", [])
            if incidents:
                target = random.choice(incidents)
                status = random.choice(["confirmed", "false_positive", "new"])
                rp = requests.patch(
                    f"{BASE}/incidents/{target['incident_id']}/status",
                    json={"status": status, "reviewed_by": "stress-test"},
                    timeout=10,
                )
                rp.raise_for_status()
                with counters_lock:
                    counters["patches"] += 1
        except Exception as e:
            log_error("patcher", e)
        time.sleep(0.2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration-seconds", type=int, default=600)
    args = parser.parse_args()

    stop_at = time.time() + args.duration_seconds
    threads = [
        threading.Thread(target=writer_loop, args=(stop_at,), daemon=True),
        threading.Thread(target=writer_loop, args=(stop_at,), daemon=True),  # 2 writer threads for real write contention
        threading.Thread(target=reader_loop, args=(stop_at,), daemon=True),
        threading.Thread(target=reader_loop, args=(stop_at,), daemon=True),
        threading.Thread(target=patcher_loop, args=(stop_at,), daemon=True),
    ]
    print(f"Starting {args.duration_seconds}s concurrency test: 2 writer threads, 2 reader threads, 1 patcher thread...")
    t0 = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.time() - t0

    print(f"\nDone in {elapsed:.1f}s")
    print(f"Counters: {counters}")
    print(f"Total errors: {len(errors)}")
    locked_errors = [e for e in errors if "locked" in e.lower()]
    print(f"'database is locked' errors: {len(locked_errors)}")
    if errors:
        print("\nFirst 10 errors:")
        for e in errors[:10]:
            print(" -", e)
    else:
        print("\nNo errors of any kind.")


if __name__ == "__main__":
    main()
