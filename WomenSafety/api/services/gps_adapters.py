"""GPS source adapters: ONE small adapter per source type behind a common interface.

    adapter.read() -> Optional[Fix]      (raises on transport errors; None = reachable but no fix in the reply)

!!! VERIFIED AGAINST SIMULATION ONLY !!!  Both formats below are assumptions taken from the apps'
documentation/behaviour, exercised only against the mock servers in tests/test_phone_location.py. If
scripts/check_phone_gps.py shows a real phone answers in a different shape, the fix is local to the
`parse()` of the matching adapter in THIS file.

Privacy: adapters never log or print coordinates, hosts or credentials.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Optional

import requests

from api.models.camera import INDIA_BBOX

HTTP_TIMEOUT_S = 4.0


@dataclass
class Fix:
    lat: float
    lon: float
    accuracy_m: Optional[float]
    fix_ts: float          # epoch seconds of the fix itself (receipt time if the phone gave none)

    @property
    def age_s(self) -> float:
        return max(0.0, time.time() - self.fix_ts)

    @property
    def in_india(self) -> bool:
        return INDIA_BBOX["min_lat"] <= self.lat <= INDIA_BBOX["max_lat"] and INDIA_BBOX["min_lng"] <= self.lon <= INDIA_BBOX["max_lng"]


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
    return v / 1000.0 if v > 1e11 else v  # milliseconds or seconds


class GpsAdapter:
    name = "adapter"

    def read(self) -> Optional[Fix]:  # pragma: no cover - interface
        raise NotImplementedError


class IPWebcamHttpAdapter(GpsAdapter):
    """IP Webcam (Android) HTTP endpoints on the phone's own host. VERIFIED AGAINST SIMULATION ONLY.

    Assumed shapes:
      /gps.json                  {"latitude": .., "longitude": .., "accuracy": .., "time": <ms>}   (also lat/lng/lon keys)
      /sensors.json?sense=gps    {"gps": {"data": [[<ts>, [lat, lon, ...]]]}}  (newest entry last)
    Tried in order; the first that yields a fix is remembered by the poller.
    """
    PATHS = ("/gps.json", "/sensors.json?sense=gps", "/sensors.json")

    def __init__(self, base_url: str, auth=None, path: str = "/gps.json"):
        self.base_url, self.auth, self.path = base_url, auth, path
        self.name = f"ipwebcam {path}"

    @staticmethod
    def parse(payload, received_at: float) -> Optional[Fix]:
        if isinstance(payload, dict):
            lat = next((_num(payload[k]) for k in ("latitude", "lat") if _num(payload.get(k)) is not None), None)
            lon = next((_num(payload[k]) for k in ("longitude", "lng", "lon") if _num(payload.get(k)) is not None), None)
            if lat is not None and lon is not None:
                acc = next((_num(payload[k]) for k in ("accuracy", "acc") if _num(payload.get(k)) is not None), None)
                return Fix(lat, lon, acc, _epoch(payload.get("time") or payload.get("timestamp"), received_at))
            for key, value in payload.items():
                if "gps" in str(key).lower() or isinstance(value, (dict, list)):
                    found = IPWebcamHttpAdapter.parse(value, received_at)
                    if found:
                        return found
        elif isinstance(payload, list):
            if len(payload) == 2 and isinstance(payload[1], list) and len(payload[1]) >= 2 and _num(payload[1][0]) is not None and _num(payload[1][1]) is not None:
                values = payload[1]
                return Fix(_num(values[0]), _num(values[1]), _num(values[3]) if len(values) > 3 else None, _epoch(payload[0], received_at))
            for item in reversed(payload):
                found = IPWebcamHttpAdapter.parse(item, received_at)
                if found:
                    return found
        return None

    def read(self) -> Optional[Fix]:
        response = requests.get(self.base_url + self.path, timeout=HTTP_TIMEOUT_S, auth=self.auth)
        response.raise_for_status()
        return self.parse(response.json(), time.time())

    @classmethod
    def candidates(cls, base_url: str, auth=None):
        return [cls(base_url, auth, p) for p in cls.PATHS]


class SensorServerWsAdapter(GpsAdapter):
    """SensorServer (Android) WebSocket, e.g. ws://<phone>:<port>/gps. VERIFIED AGAINST SIMULATION ONLY.

    Assumed message: JSON {"latitude": .., "longitude": .., "accuracy": .., "time": <ms>}; also accepts
    {"values": [lat, lon, ...], "timestamp": ..}. `read()` opens the socket and returns the first fix; `stream()`
    yields fixes from one long-lived connection (what the poller uses).
    """
    name = "sensorserver websocket /gps"

    def __init__(self, url: str):
        self.url = url

    @staticmethod
    def parse(message: str, received_at: float) -> Optional[Fix]:
        data = json.loads(message)
        if not isinstance(data, dict):
            return None
        lat, lon = _num(data.get("latitude")), _num(data.get("longitude"))
        if lat is not None and lon is not None:
            return Fix(lat, lon, _num(data.get("accuracy")), _epoch(data.get("time") or data.get("timestamp"), received_at))
        values = data.get("values")
        if isinstance(values, list) and len(values) >= 2 and _num(values[0]) is not None and _num(values[1]) is not None:
            return Fix(_num(values[0]), _num(values[1]), _num(values[3]) if len(values) > 3 else None,
                       _epoch(data.get("timestamp") or data.get("time"), received_at))
        return None

    def read(self) -> Optional[Fix]:
        from websockets.sync.client import connect
        with connect(self.url, open_timeout=HTTP_TIMEOUT_S, close_timeout=1) as ws:
            return self.parse(ws.recv(timeout=6), time.time())

    def stream(self, stop):
        """Yield fixes until `stop` (threading.Event) is set or the connection drops (raises)."""
        from websockets.sync.client import connect
        with connect(self.url, open_timeout=HTTP_TIMEOUT_S, close_timeout=1) as ws:
            while not stop.is_set():
                try:
                    message = ws.recv(timeout=2)
                except TimeoutError:
                    continue
                fix = self.parse(message, time.time())
                if fix:
                    yield fix
