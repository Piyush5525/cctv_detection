"""Retention dry-run (CHANGELOG.md "CCTV Incident Capture Pipeline"
phase, Part 5). Lists which incidents' evidence is older than
RETENTION_DAYS (api/core/config.py) and would be deleted by a real
retention job -- but does NOT delete anything. No automated cleanup
exists yet; this is reporting only, so an operator can review the list
before any deletion logic is ever written.

Usage:
    python scripts/retention_dry_run.py
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.core.config import settings
from api import db


def main():
    db.init_db()
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.RETENTION_DAYS)
    all_incidents = db.list_incidents()

    to_delete = []
    for inc in all_incidents:
        event_start = datetime.fromisoformat(inc["event_start"])
        if event_start < cutoff:
            to_delete.append(inc)

    print(f"Retention policy: RETENTION_DAYS={settings.RETENTION_DAYS}, cutoff={cutoff.isoformat()}")
    print(f"Total incidents: {len(all_incidents)}")
    print(f"Would delete (dry-run, nothing actually removed): {len(to_delete)}")
    for inc in to_delete:
        evidence = inc.get("evidence", {})
        print(f"  - {inc['incident_id']} camera={inc['camera_id']} event_start={inc['event_start']} "
              f"clip={evidence.get('clip_path')}")

    if not to_delete:
        print("Nothing would be deleted under the current retention window.")


if __name__ == "__main__":
    main()
