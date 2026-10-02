"""Runs the demo sequence against a running API and prints a timeline of what each step did.

    python scripts/run_demo.py --sequence fire,crash,fall,violence,snatching --delay 25 --dry-run [--camera CAM-001]

Each step POSTs /api/v1/demo/trigger (X-Demo-Token from DEMO_TOKEN in WomenSafety/.env, never printed), then watches
the incident's notification timeline for a few seconds. A category that cannot run (clip missing, or the real
detector did not fire on the provided clip) is reported as SKIPPED with the reason: nothing is forced.

WARNING: against an API with ALERTS_ENABLED=true this sends REAL Telegram messages, and (for fire/crash, unless
--dry-run) can place a REAL call after the escalation delay. --dry-run turns on DRY RUN for the run (Telegram stays
real, calls are suppressed) and restores the previous setting at the end. Use --base-url to point at a scratch API.
"""
import argparse
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
ALIASES = {"crash": "road_accident", "violence": "assault", "snatch": "snatching", "snatching": "snatching"}
HOW = {"fire": "auto-call after the delay unless acknowledged", "road_accident": "auto-call after the delay unless acknowledged",
       "fall": "EXPERIMENTAL: Telegram + dashboard, NO auto-call (Escalate now only)",
       "assault": "EXPERIMENTAL: Telegram + dashboard, NO auto-call (Escalate now only)",
       "snatching": "EXPERIMENTAL: Telegram + dashboard, NO auto-call (Escalate now only)"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sequence", default="fire,crash,fall,violence,snatching")
    ap.add_argument("--delay", type=float, default=25.0, help="seconds between triggers (default 25)")
    ap.add_argument("--dry-run", action="store_true", help="turn DRY RUN on for this run (calls suppressed, Telegram real)")
    ap.add_argument("--camera", default="CAM-001")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--watch", type=float, default=6.0, help="seconds to watch each incident's notification timeline")
    args = ap.parse_args()

    token = (dotenv_values(ROOT / ".env").get("DEMO_TOKEN") or os.environ.get("DEMO_TOKEN") or "").strip()
    if not token:
        print("DEMO_TOKEN is unset in WomenSafety/.env: the trigger routes are disabled. Stopping.")
        return 2
    api = args.base_url.rstrip("/") + "/api/v1"
    hdr = {"X-Demo-Token": token}
    started = time.time()

    def stamp() -> str:
        return f"[+{time.time() - started:6.1f}s]"

    try:
        state = requests.get(f"{api}/demo-state", timeout=15).json()
    except Exception as exc:
        print(f"API not reachable at {args.base_url} ({type(exc).__name__}). Stopping.")
        return 2
    avail = {c["category"]: c for c in state["categories"]}
    prev_dry = state["dry_run"]
    print(f"{stamp()} demo_mode={state['demo_mode']} dry_run={prev_dry} camera={args.camera}")
    if args.dry_run and not prev_dry:
        requests.post(f"{api}/demo/dry-run", json={"enabled": True}, headers=hdr, timeout=15)
        print(f"{stamp()} DRY RUN turned ON for this run (will be restored at the end)")
    rows = []
    steps = [ALIASES.get(s.strip(), s.strip()) for s in args.sequence.split(",") if s.strip()]
    try:
        for i, cat in enumerate(steps):
            info = avail.get(cat)
            if info is None:
                print(f"{stamp()} {cat}: SKIPPED (unknown category)")
                rows.append((cat, "skipped", "unknown category"))
            elif not info["enabled"]:
                print(f"{stamp()} {info['label']}: SKIPPED ({info['reason']})")
                rows.append((cat, "skipped", info["reason"]))
            else:
                print(f"{stamp()} {info['label']}: triggering ({HOW[cat]})")
                r = requests.post(f"{api}/demo/trigger", json={"camera_id": args.camera, "category": cat}, headers=hdr, timeout=180)
                if r.status_code != 200:
                    detail = r.json().get("detail", r.text[:120]) if r.headers.get("content-type", "").startswith("application/json") else r.text[:120]
                    print(f"{stamp()} {info['label']}: NOT CREATED, HTTP {r.status_code}: {detail}")
                    rows.append((cat, f"HTTP {r.status_code}", str(detail)))
                else:
                    inc = r.json()
                    iid = inc["incident_id"]
                    seen = set()
                    end = time.time() + args.watch
                    while time.time() < end:
                        full = requests.get(f"{api}/incidents/{iid}", timeout=15).json()
                        for n in full.get("notifications", []):
                            key = (n["channel"], n["status"], n["at"])
                            if key not in seen:
                                seen.add(key)
                                print(f"{stamp()}    {n['channel']:9s} {n['status']:11s} {n.get('detail') or ''}")
                        time.sleep(1.0)
                    plan = full.get("dispatch_plan") or {}
                    primary = next((a for a in plan.get("assignments", []) if a.get("role") == "primary"), {})
                    pname = (primary.get("service") or {}).get("title") or primary.get("status", "n/a")
                    det = full.get("detection", {})
                    print(f"{stamp()}    incident {iid[:8]} category={full['category']} source={full['source']} experimental={det.get('experimental', False)} "
                          f"score={det.get('peak_confidence')} thr={det.get('threshold_applied')} primary service ({primary.get('service_category')}): {pname}")
                    rows.append((cat, "created", f"{iid[:8]} calls={[n['status'] for n in full['notifications'] if n['channel'] == 'call']}"))
            if i < len(steps) - 1:
                print(f"{stamp()} waiting {args.delay:g}s ...")
                time.sleep(args.delay)
    finally:
        if args.dry_run and not prev_dry:
            requests.post(f"{api}/demo/dry-run", json={"enabled": False}, headers=hdr, timeout=15)
            print(f"{stamp()} DRY RUN restored to OFF")
    print("\nSUMMARY")
    for cat, status, detail in rows:
        print(f"  {cat:14s} {status:10s} {detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
