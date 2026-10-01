"""Device GPS for demo phones with a fixed-coordinate fallback.

LOCATION_MODE (config): "fixed" (DEFAULT) = nothing in this module runs and nothing changes;
"auto" = device GPS when a fix is fresh and accurate enough, else the camera's .env coordinates;
"device" = device GPS only. Applies ONLY to phone cameras: replay / file-based sample cameras and showcase
data always keep their registry coordinates.

A background poller per phone keeps the last fixes (history 10), reconnects with backoff, and the position
used is the median of recent *acceptable* fixes (fresh <= MAX_FIX_AGE_S, accurate <= MAX_ACCURACY_M, inside
the India bounding box); a single jump > LOCATION_JUMP_M is ignored unless the next fix confirms it.
Source parsing lives in api/services/gps_adapters.py. Raw coordinates are never logged here.
"""
from __future__ import annotations

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

from api.core.config import settings
from api.models.camera import Camera, all_cameras, resolve_stream_source
from api.services.gps_adapters import Fix, GpsAdapter, IPWebcamHttpAdapter, SensorServerWsAdapter

HISTORY = 10


def distance_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = radians(lat1), radians(lat2)
    a = sin((p2 - p1) / 2) ** 2 + cos(p1) * cos(p2) * sin(radians(lon2 - lon1) / 2) ** 2
    return 2 * r * atan2(sqrt(a), sqrt(1 - a))


@dataclass
class Resolved:
    lat: float
    lon: float
    source: str                      # "device_gps" | "camera_registry"
    accuracy_m: Optional[float] = None
    fix_age_s: Optional[float] = None


def _prefix(camera: Camera) -> Optional[str]:
    m = re.fullmatch(r"env:(.+)_URL", camera.stream_source)
    return m.group(1) if m else None


def build_adapters(camera: Camera) -> list[GpsAdapter]:
    """Sources to try for a phone, in order. URLs/credentials come from .env only, held in memory."""
    adapters: list[GpsAdapter] = []
    prefix = _prefix(camera)
    ws_url = os.environ.get(f"{prefix}_GPS_URL") if prefix else None
    if ws_url:
        adapters.append(SensorServerWsAdapter(ws_url))
    try:
        parts = urlsplit(resolve_stream_source(camera))
    except ValueError:
        parts = None
    if parts and parts.scheme in ("http", "https") and parts.hostname:
        netloc = f"{parts.hostname}:{parts.port}" if parts.port else parts.hostname
        auth = (parts.username, parts.password) if parts.username else None
        adapters.extend(IPWebcamHttpAdapter.candidates(f"{parts.scheme}://{netloc}", auth))
    return adapters


def candidate_sources(camera: Camera) -> list[tuple[str, Callable[[], Optional[Fix]]]]:
    """For scripts/check_phone_gps.py: (name, probe) pairs."""
    return [(a.name, a.read) for a in build_adapters(camera)]


def _effective(fixes: list[Fix]) -> list[Fix]:
    """Drop a lone jump > LOCATION_JUMP_M; accept it when the next fix confirms it. Oldest -> newest."""
    jump = settings.LOCATION_JUMP_M
    if len(fixes) < 3:
        return fixes
    head, tail = fixes[:-2], fixes[-2:]
    anchor_lat = statistics.median(f.lat for f in head)
    anchor_lon = statistics.median(f.lon for f in head)
    far = [distance_m(f.lat, f.lon, anchor_lat, anchor_lon) > jump for f in tail]
    if not any(far):
        return fixes
    if all(far) and distance_m(tail[0].lat, tail[0].lon, tail[1].lat, tail[1].lon) <= jump:
        return tail  # confirmed move: the old position is stale
    return head + [f for f, is_far in zip(tail, far) if not is_far]


class PhoneLocation:
    """Latest fixes + smoothing for one phone. `feed()` is also what tests use."""

    def __init__(self, camera_id: str, adapters: Optional[list[GpsAdapter]] = None, on_cell_change: Optional[Callable] = None):
        self.camera_id, self.adapters, self.on_cell_change = camera_id, adapters or [], on_cell_change
        self.history: deque[Fix] = deque(maxlen=HISTORY)
        self._lock, self._stop = threading.Lock(), threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.status = "no fix yet"
        self._last_cell = None

    def feed(self, fix: Fix) -> None:
        if not fix.in_india:  # reject outside the India bounding box
            self.status = "rejected: outside India"
            return
        with self._lock:
            self.history.append(fix)
        self.status = "ok"
        self._maybe_cell_change()

    def acceptable(self) -> list[Fix]:
        with self._lock:
            fixes = list(self.history)
        return [f for f in fixes if f.age_s <= settings.MAX_FIX_AGE_S and f.accuracy_m is not None and f.accuracy_m <= settings.MAX_ACCURACY_M]

    def position(self) -> Optional[Resolved]:
        fixes = _effective(self.acceptable())
        if not fixes:
            return None
        window = fixes[-max(1, settings.SMOOTH_FIXES):]
        return Resolved(statistics.median(f.lat for f in window), statistics.median(f.lon for f in window), "device_gps",
                        float(statistics.median(f.accuracy_m for f in window)), round(window[-1].age_s, 1))

    def _maybe_cell_change(self) -> None:
        pos = self.position()
        if not pos or not self.on_cell_change:
            return
        cell = (round(pos.lat, 3), round(pos.lon, 3))
        if cell != self._last_cell:
            self._last_cell = cell
            try:
                self.on_cell_change(self.camera_id, pos.lat, pos.lon)
            except Exception:
                pass

    # ── background polling (reconnect + backoff) ──
    def start(self) -> None:
        if self.thread or not self.adapters:
            return
        self.thread = threading.Thread(target=self._run, name=f"gps-{self.camera_id}", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        backoff, working = 1.0, None
        while not self._stop.is_set():
            try:
                candidates = [working] if working else self.adapters
                got = False
                for adapter in candidates:
                    if isinstance(adapter, SensorServerWsAdapter):
                        for fix in adapter.stream(self._stop):  # long-lived connection
                            got, working, backoff = True, adapter, 1.0
                            self.feed(fix)
                        continue
                    try:
                        fix = adapter.read()
                    except Exception:
                        continue
                    if fix:
                        got, working, backoff = True, adapter, 1.0
                        self.feed(fix)
                        break
                if not got:
                    working = None
                    self.status = "no GPS source reachable"
                    self._stop.wait(backoff)
                    backoff = min(backoff * 2, 15.0)
                else:
                    self._stop.wait(settings.LOCATION_POLL_S)
            except Exception:  # dropped connection etc.: keep history, retry with backoff
                working = None
                self.status = "connection lost; retrying"
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 15.0)


class LocationManager:
    def __init__(self) -> None:
        self.providers: dict[str, PhoneLocation] = {}

    def start(self) -> None:
        if settings.LOCATION_MODE == "fixed" or self.providers:
            return  # default: nothing runs, nothing changes
        from api.services import nearby_services
        for camera in all_cameras():
            if camera.camera_type != "phone" or not camera.enabled:
                continue
            provider = PhoneLocation(camera.camera_id, build_adapters(camera),
                                     on_cell_change=lambda cid, lat, lon, place=camera.place_text: nearby_services.warm_async(lat, lon, place))
            self.providers[camera.camera_id] = provider
            provider.start()
            if camera.latitude is not None:  # phone start-up: warm the cache for its fixed position too
                nearby_services.warm_async(camera.latitude, camera.longitude, camera.place_text)

    def stop(self) -> None:
        for provider in self.providers.values():
            provider.stop()
        self.providers.clear()

    def device_position(self, camera_id: str) -> Optional[Resolved]:
        provider = self.providers.get(camera_id)
        return provider.position() if provider else None


location_manager = LocationManager()


def resolve_location(camera: Camera) -> Optional[Resolved]:
    """The location to snapshot / display for `camera` right now, or None (camera is then offline/quarantined).
    Device GPS is considered ONLY for phone cameras and only when LOCATION_MODE is auto/device; everything
    else (sample cameras, replays, showcase, fixed mode) uses the registry coordinates."""
    mode = settings.LOCATION_MODE
    if camera.camera_type == "phone" and mode in ("auto", "device"):
        device = location_manager.device_position(camera.camera_id)
        if device:
            return device
        if mode == "device":
            return None
    if camera.latitude is not None and camera.longitude is not None:
        return Resolved(camera.latitude, camera.longitude, "camera_registry")
    return None


def location_fields(camera: Camera, resolved: Optional[Resolved]) -> dict:
    """Snapshot / display fields. EMPTY unless the camera is a phone and LOCATION_MODE != fixed, so incidents,
    labels and status output are unchanged in the default mode and for sample cameras."""
    if resolved is None or camera.camera_type != "phone" or settings.LOCATION_MODE == "fixed":
        return {}
    return {"location_source": resolved.source, "location_accuracy_m": resolved.accuracy_m, "location_fix_age_s": resolved.fix_age_s}
