"""Camera registry: fixed CCTV and demo-phone locations loaded from
config/cameras.json. The product is CCTV-only (see CHANGELOG.md "CCTV
Incident Capture Pipeline" phase) -- every incident's location comes
from this registry, snapshotted onto the incident at creation time.

stream_source may be an RTSP/HTTP URL, a device index (e.g. "0" for a local
webcam), a path to a video file used to simulate a camera feed, or an env
reference ("env:PHONE_CAM001_URL"). latitude / longitude may also be env
references ("env:PHONE_CAM001_LAT"). Env references are resolved at runtime and
validated (numeric, inside the India bounding box); if one is unset or invalid
the camera is reported offline with a clear error -- never a default coordinate.

Secrets hygiene: credentials must never be written into this file. A phone app
that needs a login keeps it in <PREFIX>_USER / <PREFIX>_PASSWORD env vars next
to the <PREFIX>_URL one; the credentialed URL is built in memory at connect
time only. Neither the stream URL, the credentials nor the coordinates are
ever logged or put in an error message (only env var NAMES may be).
"""
import json
import os
import re
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import quote, urlsplit, urlunsplit

from pydantic import BaseModel, field_validator, model_validator

import api.core.config  # noqa: F401  (loads .env so env: references resolve in every entry point)

CAMERAS_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "cameras.json"

# Same bounding box used elsewhere in this project for scraped-incident
# geocoding sanity checks (scripts/scrape_pipeline.py) -- a camera whose
# registered coordinates fall outside India is almost certainly a typo,
# not a real installation, and should fail loudly at load time rather
# than silently entering the registry.
INDIA_BBOX = {"min_lat": 6.0, "max_lat": 37.5, "min_lng": 68.0, "max_lng": 97.5}


class Camera(BaseModel):
    camera_id: str
    name: str
    place_text: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    latitude_ref: Optional[str] = None   # "env:VAR" when the file holds a reference instead of a number
    longitude_ref: Optional[str] = None
    location_error: Optional[str] = None  # set when an env reference is unset/invalid (camera stays offline)
    stream_source: str  # URL, device index as string, video file path, or "env:VAR"
    camera_type: Literal["cctv", "phone"] = "cctv"
    location_basis: Literal["real_installation", "simulated_placement"] = "real_installation"
    enabled: bool = True
    sample: bool = False
    field_of_view_note: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _split_env_refs(cls, data):
        if isinstance(data, dict):
            data = dict(data)
            for key in ("latitude", "longitude"):
                value = data.get(key)
                if isinstance(value, str):
                    if not value.startswith("env:") or len(value) <= 4:
                        raise ValueError(f"{key} must be a number or an 'env:VAR' reference")
                    data[f"{key}_ref"] = value
                    data[key] = None
        return data

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v):
        return v.strip()

    @property
    def display_name(self) -> str:
        # Don't double the prefix if the registered name already has it.
        if self.camera_type != "phone":
            return self.name
        prefix = "Demo phone camera"
        if self.name.lower().startswith(prefix.lower()):
            return self.name
        return f"{prefix} - {self.name}"

    @field_validator("latitude")
    @classmethod
    def _lat_in_india(cls, v):
        if v is not None and not (INDIA_BBOX["min_lat"] <= v <= INDIA_BBOX["max_lat"]):
            raise ValueError("latitude is outside the India bounding box -- refusing to register this camera")
        return v

    @field_validator("longitude")
    @classmethod
    def _lng_in_india(cls, v):
        if v is not None and not (INDIA_BBOX["min_lng"] <= v <= INDIA_BBOX["max_lng"]):
            raise ValueError("longitude is outside the India bounding box -- refusing to register this camera")
        return v

    @model_validator(mode="after")
    def _numeric_coordinates_present(self):
        if (self.latitude is None and not self.latitude_ref) or (self.longitude is None and not self.longitude_ref):
            raise ValueError("latitude and longitude are required (a number or an env: reference)")
        return self

    @field_validator("stream_source")
    @classmethod
    def _no_credentials_in_file(cls, v):
        # Catches the common accident of pasting a real rtsp://user:pass@host
        # URL straight into the checked-in config file.
        if re.search(r"[a-z]+://[^/@]+:[^/@]+@", v):
            raise ValueError(
                "stream_source appears to contain embedded credentials -- "
                "use an env-var reference (e.g. 'env:PHONE_CAM001_URL') and, if the app needs a login, "
                "<PREFIX>_USER / <PREFIX>_PASSWORD env vars; credentials must never be committed to config/cameras.json"
            )
        return v


def _resolve_coordinate(ref: str, low: float, high: float, label: str) -> tuple[Optional[float], Optional[str]]:
    """(value, error). The error names the env var but never its value."""
    var = ref[len("env:"):]
    raw = os.environ.get(var)
    if raw is None or not raw.strip():
        return None, f"{label} env var {var} is unset"
    try:
        value = float(raw.strip())
    except ValueError:
        return None, f"{label} env var {var} is not a number"
    if not (low <= value <= high) or value != value:
        return None, f"{label} env var {var} is outside the India bounding box"
    return value, None


def _with_resolved_location(cam: Camera) -> Camera:
    """Fill latitude/longitude from env references (re-read each call). On any
    problem both stay None and location_error says which variable is at fault."""
    if not (cam.latitude_ref or cam.longitude_ref):
        return cam
    errors = []
    lat, lng = cam.latitude, cam.longitude
    if cam.latitude_ref:
        lat, err = _resolve_coordinate(cam.latitude_ref, INDIA_BBOX["min_lat"], INDIA_BBOX["max_lat"], "latitude")
        if err:
            errors.append(err)
    if cam.longitude_ref:
        lng, err = _resolve_coordinate(cam.longitude_ref, INDIA_BBOX["min_lng"], INDIA_BBOX["max_lng"], "longitude")
        if err:
            errors.append(err)
    if errors:
        return cam.model_copy(update={"latitude": None, "longitude": None, "location_error": "; ".join(errors)})
    return cam.model_copy(update={"latitude": lat, "longitude": lng, "location_error": None})


_camera_registry: dict[str, Camera] = {}


def load_cameras(path: Path = CAMERAS_CONFIG_PATH) -> dict[str, Camera]:
    """Loads and validates config/cameras.json. Invalid entries are
    skipped with a printed warning (reason only, never the entry's values),
    never silently substituted with a default camera."""
    global _camera_registry
    if not path.exists():
        print(f"camera registry: no config file at {path}, starting with an empty registry")
        _camera_registry = {}
        return _camera_registry

    raw = json.loads(path.read_text(encoding="utf-8"))
    registry = {}
    for entry in raw.get("cameras", []):
        try:
            cam = Camera(**entry)
            registry[cam.camera_id] = cam
        except Exception as e:
            reasons = "; ".join(str(err.get("msg", "invalid")) for err in getattr(e, "errors", lambda: [])()) or type(e).__name__
            print(f"camera registry: skipping invalid entry {entry.get('camera_id', '?')}: {reasons}")
    _camera_registry = registry
    return _camera_registry


def get_camera(camera_id: str) -> Optional[Camera]:
    if not _camera_registry:
        load_cameras()
    cam = _camera_registry.get(camera_id)
    return _with_resolved_location(cam) if cam else None


def all_cameras() -> list[Camera]:
    if not _camera_registry:
        load_cameras()
    return [_with_resolved_location(c) for c in _camera_registry.values()]


def resolve_stream_source(camera: Camera) -> str:
    """Resolves a stream_source that references an env var (e.g.
    'env:PHONE_CAM001_URL') to its real value at connect time. For URL sources
    named <PREFIX>_URL, an optional <PREFIX>_PASSWORD (with <PREFIX>_USER) is
    injected into the URL in memory only. Never logs the resolved value: error
    messages carry env var NAMES only."""
    source = camera.stream_source
    if not source.startswith("env:"):
        return source
    var_name = source[len("env:"):]
    value = os.environ.get(var_name)
    if not value or not value.strip():
        raise ValueError(f"env var {var_name} is not set")
    value = value.strip()
    if var_name.endswith("_URL") and "://" in value:
        prefix = var_name[: -len("_URL")]
        password = os.environ.get(f"{prefix}_PASSWORD")
        if password:
            user = os.environ.get(f"{prefix}_USER")
            if not user:
                raise ValueError(f"env var {prefix}_USER is required when {prefix}_PASSWORD is set")
            parts = urlsplit(value)
            if "@" not in parts.netloc:  # don't override credentials already inside the env URL
                netloc = f"{quote(user, safe='')}:{quote(password, safe='')}@{parts.netloc}"
                value = urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    return value


def stream_reachable(url: str, timeout_s: float = 3.0) -> bool:
    """TCP preflight for http/rtsp streams. OpenCV's FFmpeg backend prints the full
    host:port in its connection errors and that output cannot be silenced from inside
    the process on Windows, so we never hand it an unreachable URL: this check
    fails quietly (no URL in any message) and callers just report "unreachable"."""
    import socket
    try:
        parts = urlsplit(url)
        port = parts.port or {"rtsp": 554, "https": 443}.get(parts.scheme, 80)
        with socket.create_connection((parts.hostname, port), timeout=timeout_s):
            return True
    except Exception:
        return False


# Load at import time so the registry is populated before the first request.
load_cameras()
