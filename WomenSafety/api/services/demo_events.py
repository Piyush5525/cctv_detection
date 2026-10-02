"""Scripted demo events: data/demo/demo_events.yaml.

A SCRIPTED incident is created by the demo script from one of the provided clips: the category is chosen by the script, NOT by
a detector (no detector runs on these clips, nothing is scored). This module only loads and validates the script entries:

    REPLACE_ME: true          # example marker; while present every trigger is refused
    fall:
      clip: data/demo/fall.mp4
      event_start_s: 4.0
      event_end_s: 12.0
      best_frame_s: 8.0
      place_note: optional free text

Validation (per class, so one bad entry only disables that category): the clip must be under data/demo, exist, be readable and
have a duration; 0 <= event_start_s < event_end_s <= clip duration; best_frame_s inside [event_start_s, event_end_s].
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import yaml

from api.core.config import settings

ROOT = Path(__file__).resolve().parent.parent.parent
DEMO_DIR = ROOT / "data" / "demo"

# YAML class key -> (incident category value, label shown to the operator, spoken word)
CLASSES = {
    "fall": ("fall", "Fall", "fall"),
    "violence": ("assault", "Violence", "violence"),
    "snatching": ("snatching", "Snatching", "snatching"),
}
ALIASES = {"snatch": "snatching", "assault": "violence"}      # trigger category names accepted -> YAML class key
CATEGORY_TO_KEY = {cat: key for key, (cat, _l, _s) in CLASSES.items()}
PLACEHOLDER_REASON = "REPLACE_ME: true is still in data/demo/demo_events.yaml (set the real seconds, then delete that line)"


class ScriptedUnavailable(Exception):
    """This scripted category cannot run right now; the message is the reason shown to the operator."""


@dataclass(frozen=True)
class ScriptedEvent:
    key: str
    category: str
    label: str
    spoken: str
    clip: Path
    clip_rel: str
    duration_s: float
    start_s: float
    end_s: float
    best_s: float
    place_note: Optional[str] = None


def key_for(category: str) -> str:
    """Accepts the YAML key (fall/violence/snatching), the incident category (assault) or an alias (snatch)."""
    c = str(category).lower()
    return CATEGORY_TO_KEY.get(c) or ALIASES.get(c, c)


def _number(raw, name: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(float(raw)):
        raise ScriptedUnavailable(f"{name} must be a number of seconds")
    return float(raw)


def clip_duration(path: Path) -> float:
    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            raise ScriptedUnavailable(f"clip not readable: {path.name}")
        fps, frames = cap.get(cv2.CAP_PROP_FPS) or 0.0, cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
    finally:
        cap.release()
    if fps <= 0 or frames <= 0:
        raise ScriptedUnavailable(f"clip has no readable duration: {path.name}")
    return frames / fps


def _entry(key: str, raw) -> ScriptedEvent:
    category, label, spoken = CLASSES[key]
    if not isinstance(raw, dict):
        raise ScriptedUnavailable(f"no entry for {key} in data/demo/demo_events.yaml")
    clip_rel = str(raw.get("clip") or "").replace("\\", "/")
    if not clip_rel:
        raise ScriptedUnavailable(f"{key}: clip path missing")
    clip = (ROOT / clip_rel).resolve()
    try:
        clip.relative_to(DEMO_DIR.resolve())
    except ValueError:
        raise ScriptedUnavailable(f"{key}: clip must be inside data/demo ({clip_rel})")
    if not clip.exists():
        raise ScriptedUnavailable(f"clip missing: {clip_rel}")
    duration = clip_duration(clip)
    start, end, best = (_number(raw.get(k), f"{key}.{k}") for k in ("event_start_s", "event_end_s", "best_frame_s"))
    if start < 0 or end > duration + 0.001:
        raise ScriptedUnavailable(f"{key}: event window {start:g}-{end:g} s is outside the clip (0-{duration:.1f} s)")
    if end <= start:
        raise ScriptedUnavailable(f"{key}: event_end_s must be greater than event_start_s")
    if not start <= best <= end:
        raise ScriptedUnavailable(f"{key}: best_frame_s {best:g} must be inside the event window {start:g}-{end:g} s")
    note = raw.get("place_note")
    return ScriptedEvent(key=key, category=category, label=label, spoken=spoken, clip=clip, clip_rel=clip_rel, duration_s=duration,
                         start_s=start, end_s=end, best_s=best, place_note=str(note).strip() if note else None)


def load(path: Optional[Path] = None) -> dict:
    """-> {"placeholder": bool, "file_error": str|None, "events": {key: ScriptedEvent}, "errors": {key: reason}}"""
    p = Path(path or settings.DEMO_EVENTS_PATH)
    out = {"placeholder": False, "file_error": None, "events": {}, "errors": {}}
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError("the file must be a YAML mapping")
    except OSError:
        out["file_error"] = f"{p.name} not found (create data/demo/demo_events.yaml)"
        data = {}
    except (yaml.YAMLError, ValueError) as exc:
        out["file_error"] = f"{p.name} is not valid YAML: {str(exc).splitlines()[0][:100]}"
        data = {}
    marker = data.get("REPLACE_ME")
    out["placeholder"] = marker is True or str(marker).strip().lower() == "true"
    for key in CLASSES:
        if out["file_error"]:
            out["errors"][key] = out["file_error"]
            continue
        try:
            out["events"][key] = _entry(key, data.get(key))
        except ScriptedUnavailable as exc:
            out["errors"][key] = str(exc)
    return out


def availability(category: str, path: Optional[Path] = None) -> tuple:
    """-> (enabled, reason). The REPLACE_ME marker disables every category."""
    key = key_for(category)
    if key not in CLASSES:
        return False, f"unknown category {category!r}"
    cfg = load(path)
    if cfg["placeholder"]:
        return False, PLACEHOLDER_REASON
    if key in cfg["events"]:
        return True, ""
    return False, cfg["errors"].get(key, "not configured")


def get_event(category: str, path: Optional[Path] = None) -> ScriptedEvent:
    ok, reason = availability(category, path)
    if not ok:
        raise ScriptedUnavailable(reason)
    return load(path)["events"][key_for(category)]
