"""Device GPS for demo phones, with a fixed-coordinate fallback.

Sources (per phone camera):
  (a) IP Webcam HTTP endpoints on the camera's own host: /gps.json, /sensors.json?sense=gps, /sensors.json
  (b) SensorServer WebSocket at PHONE_CAMnnn_GPS_URL (ws://<host>:<port>/gps), fields latitude, longitude, accuracy, time

A background poller per phone keeps the latest fixes (history of 10), tolerant of drops (reconnect with
backoff). The position used is the median of recent *acceptable* fixes (fresh enough, accurate enough, inside the
India bounding box); a single jump > LOCATION_JUMP_M is ignored unless the next fix confirms it.

Privacy: this module never logs or returns raw coordinates through status/error text; URLs and credentials
live only in .env and are never printed.
"""
from __future__ import annotations

import json
import os
import re
import statistics
import threading
import time
from collections import deque
from dataclasses import dataclass
from math import atan2, cos, radians, sin, sqrt
from typing import Callable, Optional
from urllib.parse import urlsplit

import requests

from api.core.config import settings
from api.models.camera import INDIA_BBOX, Camera, get_camera, resolve_stream_source

HISTORY = 10
HTTP_TIMEOUT_S = 4.0


def distance_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = radians(lat1), radians(lat2)
    a = sin((p2 - p1) / 2) ** 2 + cos(p1) * cos(p2) * sin(radians(lon2 - lon1) / 2) ** 2
    return 2 * r * atan2(sqrt(a), sqrt(1 - a))


def in_india(lat: float, lon: float) -> bool:
    return INDIA_BBOX["min_lat"] <= lat <= INDIA_BBOX["max_lat"] and INDIA_BBOX["min_lng"] <= lon <= INDIA_BBOX["max_lng"]


@dataclass
class Fix:
    lat: float
    lon: float
    accuracy_m: Optional[float]
    fix_ts: float          # epoch seconds of the fix itself (receipt time if the phone gave none)
    source: str = "device_gps"

    @property
    def age_s(self) -> float:
        return max(0.0, time.time() - self.fix_ts)

    @property
    def in_india(self) -> bool:
        return in_india(self.lat, self.lon)


# ─── parsing (formats differ between apps; be liberal in what we accept) ───
_LAT, _LON = ("latitude", "lat"), ("longitude", "lng", "lon", "long")


def _num(value):
    try:
        v = float(value)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def _epoch(value, default):
    v = _num(value)
    if v is None or v <= 0:
        return default
    return v / 1000.0 if v > 1e11 else v  # ms or s


def _find_fix(obj, received_at: float):
    if isinstance(obj, dict):
        lat = next((_num(obj[k]) for k in _LAT if k in obj and _num(obj[k]) is not None), None)
        lon = next((_num(obj[k]) for k in _LON if k in obj and _num(obj[k]) is not None), None)
        if lat is not None and lon is not None:
            acc = next((_num(obj[k]) for k in ("accuracy", "acc", "hAccuracy", "horizontalAccuracy") if k in obj and _num(obj[k]) is not None), None)
            ts = next((obj[k] for k in ("time", "timestamp", "fix_time", "ts") if k in obj), None)
            return Fix(lat, lon, acc, _epoch(ts, received_at))
        values = obj.get("values")
        if isinstance(values, list) and len(values) >= 2 and _num(values[0]) is not None and _num(values[1]) is not None:
            acc = _num(values[3]) if len(values) > 3 else None
            return Fix(_num(values[0]), _num(values[1]), acc, _epoch(obj.get("timestamp") or obj.get("time"), received_at))
        for key, value in obj.items():  # IP Webcam sensors.json: {"gps": {"data": [[ts, [lat, lon, ...]]]}}
            if "gps" in str(key).lower() or isinstance(value, (dict, list)):
                found = _find_fix(value, received_at)
                if found:
                    return found
    elif isinstance(obj, list):
        if len(obj) == 2 and isinstance(obj[1], list) and len(obj[1]) >= 2 and _num(obj[1][0]) is not None and _num(obj[1][1]) is not None:
            return Fix(_num(obj[1][0]), _num(obj[1][1]), _num(obj[1][3]) if len(obj[1]) > 3 else None, _epoch(obj[0], received_at))
        for item in reversed(obj):  # newest entry last
            found = _find_fix(item, received_at)
            if found:
                return found
    return None


def parse_fix(payload, received_at: Optional[float] = None) -> Optional[Fix]:
    return _find_fix(payload, received_at or time.time())


# ─── sources ───
def _prefix(camera: Camera) -> Optional[str]:
    m = re.fullmatch(r"env:(.+)_URL", camera.stream_source)
    return m.group(1) if m else None


def _http_endpoints(camera: Camera):
    """(base_url, auth) from the camera's stream URL; in memory only."""
    parts = urlsplit(resolve_stream_source(camera))
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None, None
    netloc = f"{parts.hostname}:{parts.port}" if parts.port else parts.hostname
    auth = (parts.username, parts.password) if parts.username else None
    return f"{parts.scheme}://{netloc}", auth


def http_fix(base: str, auth, path: str) -> Optional[Fix]:
    response = requests.get(base + path, timeout=HTTP_TIMEOUT_S, auth=auth)
    response.raise_for_status()
    return parse_fix(response.json())


def ws_fix(url: str, timeout_s: float = 6.0) -> Optional[Fix]:
    from websockets.sync.client import connect
    with connect(url, open_timeout=HTTP_TIMEOUT_S, close_timeout=1) as ws:
        return parse_fix(json.loads(ws.recv(timeout=timeout_s)))


def candidate_sources(camera: Camera) -> list[tuple[str, Callable[[], Optional[Fix]]]]:
    out: list[tuple[str, Callable[[], Optional[Fix]]]] = []
    try:
        base, auth = _http_endpoints(camera)
    except ValueError:
        base, auth = None, None
    if base:
        for path in ("/gps.json", "/sensors.json?sense=gps", "/sensors.json"):
            out.append((f"ipwebcam {path.split('?')[0]}" + ("?sense=gps" if "?" in path else ""), lambda p=path: http_fix(base, auth, p)))
    prefix = _prefix(camera)
    ws_url = os.environ.get(f"{prefix}_GPS_URL") if prefix else None
    if ws_url:
        out.append(("sensorserver websocket /gps", lambda: ws_fix(ws_url)))
    return out
