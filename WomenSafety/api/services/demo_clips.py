"""Which demo categories can be triggered from the dashboard, and why not when they can't.

Fire and crash use the stored sample clips (always available). Fall / violence / snatching use ONLY the three
provided clips in data/demo/ and are enabled only if (1) the clip exists AND (2) the last run of
scripts/demo_clips_check.py showed the REAL detector fired on exactly that file (recorded with the file's SHA-256, so a
replaced clip is "not verified" until the check is rerun). Nothing here forces or fakes a detection.
"""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent.parent
RECORD_PATH = ROOT / "outputs" / "demo_clip_check.json"

# category value -> (detector name, clip path relative to the project root, label shown to the operator)
ACTION_DEMO = {
    "fall": ("fall", "data/demo/fall.mp4", "Fall"),
    "assault": ("violence", "data/demo/violence.mp4", "Violence"),
    "snatching": ("snatch", "data/demo/snatch.mp4", "Snatching"),
}
ALIASES = {"violence": "assault", "snatch": "snatching"}
BASE_CATEGORIES = [("fire", "Fire"), ("road_accident", "Crash")]

_hash_cache: dict = {}
_lock = threading.Lock()


def sha256_of(path: Path) -> str:
    st = path.stat()
    key = (str(path), st.st_mtime_ns, st.st_size)
    with _lock:
        if key not in _hash_cache:
            h = hashlib.sha256()
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            _hash_cache[key] = h.hexdigest()
        return _hash_cache[key]


def load_record(path: Optional[Path] = None) -> dict:
    p = path or RECORD_PATH
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_record(results: dict, path: Optional[Path] = None) -> None:
    """results: category -> {"fired": bool, "peak_score": float, "threshold": float}; hashes the clip files now."""
    p = path or RECORD_PATH
    rec = {}
    for cat, r in results.items():
        _det, clip, _label = ACTION_DEMO[cat]
        f = ROOT / clip
        rec[cat] = {**r, "clip": clip, "sha256": sha256_of(f) if f.exists() else None, "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rec, indent=1), encoding="utf-8")


def availability(category: str, record_path: Optional[Path] = None) -> tuple:
    """-> (enabled, reason). Fire and crash: always. Fall / violence / snatching are SCRIPTED demo incidents: enabled when the clip
    and its entry in data/demo/demo_events.yaml are valid (and the REPLACE_ME marker is gone). No detector is consulted."""
    category = ALIASES.get(category, category)
    if category in ("fire", "road_accident", "crash"):
        return True, ""
    if category not in ACTION_DEMO:
        return False, f"unknown category {category!r}"
    from api.services import demo_events
    return demo_events.availability(category)


def categories(record_path: Optional[Path] = None) -> list:
    from api.services import demo_events
    out = [{"category": c, "label": label, "enabled": True, "reason": "", "experimental": False, "scripted": False} for c, label in BASE_CATEGORIES]
    cfg = demo_events.load()                       # one load (opens each clip once) for all three
    for cat, (_det, _clip, label) in ACTION_DEMO.items():
        key = demo_events.key_for(cat)
        if cfg["placeholder"]:
            ok, reason = False, demo_events.PLACEHOLDER_REASON
        elif key in cfg["events"]:
            ok, reason = True, ""
        else:
            ok, reason = False, cfg["errors"].get(key, "not configured")
        out.append({"category": cat, "label": label, "enabled": ok, "reason": reason, "experimental": True, "scripted": True})
    return out
