"""Session audit trail for operator/demo actions (toggles, dry-run, triggers, resets).

In-memory ring (what the dashboard shows) plus an append-only JSON-lines file under outputs/ (git-ignored), so a
rehearsal can be reviewed afterwards. Never records secrets, URLs, phone numbers or coordinates: callers pass short
plain-text details only.
"""
from __future__ import annotations

import json
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

PATH = Path(__file__).resolve().parent.parent.parent / "outputs" / "session_audit.jsonl"
_lock = threading.Lock()
_ring: deque = deque(maxlen=200)
_path: Optional[Path] = PATH


def set_path(path: Optional[Path]) -> None:
    """Tests point this at a temp file (or None to keep the trail in memory only)."""
    global _path
    _path = path


def record(action: str, detail: str = "", actor: str = "operator") -> dict:
    entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "actor": actor, "action": action, "detail": detail}
    with _lock:
        _ring.append(entry)
        if _path is not None:
            try:
                _path.parent.mkdir(parents=True, exist_ok=True)
                with open(_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except OSError:
                pass   # the in-memory trail still has it
    return entry


def entries(limit: int = 50) -> list:
    with _lock:
        return list(_ring)[-limit:][::-1]   # newest first


def clear() -> None:
    with _lock:
        _ring.clear()
