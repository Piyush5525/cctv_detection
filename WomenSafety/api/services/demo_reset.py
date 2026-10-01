"""Fix pass item 10: reset the demo DB / load demo/showcase.db.

Used by scripts/reset_demo.py and the dashboard's Demo Controls (via
/api/v1/demo/reset and /api/v1/demo/showcase). Always backs up the current DB
first (backups/incidents_<ts>_pre_reset.db). Works through SQLite (not by
swapping files) so a running API with open short-lived connections is safe.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from api import db

ROOT = Path(__file__).parent.parent.parent
SHOWCASE_DB = ROOT / "demo" / "showcase.db"
BACKUP_DIR = ROOT / "backups"


class ShowcaseMissing(FileNotFoundError):
    pass


def reset(load_showcase: bool = False, showcase_path: Path = SHOWCASE_DB) -> dict:
    if load_showcase and not showcase_path.exists():
        raise ShowcaseMissing(f"{showcase_path.name} not built yet; run scripts/build_showcase.py with 5 candidate ids")
    db.init_db()
    backup = BACKUP_DIR / f"incidents_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_pre_reset.db"
    backed_up_rows = db.backup_to(backup)
    db.clear_all()
    loaded = 0
    if load_showcase:
        src = sqlite3.connect(f"file:{showcase_path}?mode=ro", uri=True)
        try:
            for incident_id, camera_id, category, status, source, event_start, data in src.execute(
                    "SELECT incident_id, camera_id, category, status, source, event_start, data FROM incidents"):
                db.insert_incident(incident_id, camera_id, category, status, source, event_start, json.loads(data))
                loaded += 1
        finally:
            src.close()
    try:  # forget cooldowns / pending escalation timers from the previous run
        from api.services.notification_service import notification_service
        notification_service.reset_state()
    except Exception:
        pass
    return {"backup": backup.relative_to(ROOT).as_posix(), "backed_up_rows": backed_up_rows, "loaded_showcase_rows": loaded}
