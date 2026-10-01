"""Restores incidents from incidents_backup.json (created by the same
session's backup step) into the running backend via the normal create API.
Use this after any backend restart, since incident storage is in-memory
only and a restart otherwise loses everything.

Usage:
    python scripts/restore_incidents_backup.py
"""
import json
import sys
from pathlib import Path

import requests

BASE = "http://localhost:8000/api/v1/incidents"
BACKUP_FILE = Path(__file__).parent.parent / "incidents_backup.json"


def main():
    if not BACKUP_FILE.exists():
        print(f"No backup file found at {BACKUP_FILE}", file=sys.stderr)
        sys.exit(1)

    incidents = json.loads(BACKUP_FILE.read_text(encoding="utf-8"))
    print(f"Restoring {len(incidents)} incidents from backup...")

    # Skip restore if the backend already has data -- avoids silently
    # doubling everything if this is run against a backend that never
    # actually lost its state.
    existing = requests.get(BASE, params={"page": 1, "page_size": 1}).json()
    if existing.get("total", 0) > 0:
        print(f"Backend already has {existing['total']} incidents -- refusing to restore on top of existing data.")
        print("If you really want to restore anyway, clear existing incidents first.")
        sys.exit(1)

    created = 0
    failed = 0
    for inc in incidents:
        payload = {
            "incident_type": inc["incident_type"],
            "severity": inc["severity"],
            "confidence": inc["confidence"],
            "timestamp": inc["timestamp"],
            "location": inc["location"],
            "detection_data": inc.get("detection_data", {}),
            "thumbnail_path": inc.get("thumbnail_path"),
        }
        resp = requests.post(BASE, json=payload)
        if resp.status_code in (200, 201):
            created += 1
        else:
            failed += 1
            print(f"FAILED to restore {inc['incident_id']}: {resp.status_code} {resp.text[:200]}")

    print(f"Restored {created}/{len(incidents)} incidents ({failed} failed)")


if __name__ == "__main__":
    main()
