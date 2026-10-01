"""Camera registry: fixed CCTV and demo-phone locations loaded from
config/cameras.json. The product is CCTV-only (see CHANGELOG.md "CCTV
Incident Capture Pipeline" phase) -- every incident's location comes
from this registry, snapshotted onto the incident at creation time.

stream_source may be an RTSP URL, a device index (e.g. "0" for a local
webcam), or a path to a video file used to simulate a camera feed for
testing/demo. RTSP credentials must never be written into this file or
logged -- if a stream needs a username/password, stream_source here
should be a placeholder like "rtsp://CAM3_HOST/stream" and the real
credentialed URL is built at connect time from an env var (e.g.
CAM3_RTSP_URL), never persisted to disk in this config or printed.
"""
import json
import re
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, field_validator

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
    latitude: float
    longitude: float
    stream_source: str  # RTSP URL placeholder, device index as string, or video file path
    camera_type: Literal["cctv", "phone"] = "cctv"
    location_basis: Literal["real_installation", "simulated_placement"] = "real_installation"
    enabled: bool = True
    sample: bool = False
    field_of_view_note: Optional[str] = None

    @field_validator("name")
    @classmethod
    def _phone_name_is_explicit(cls, v, info):
        # The actual UI label is normalised in display_name below; allow a
        # user-entered suffix such as "Entrance" without hiding its nature.
        return v.strip()

    @property
    def display_name(self) -> str:
        # Fix pass: don't double the prefix if the registered name already has it.
        if self.camera_type != "phone":
            return self.name
        prefix = "Demo phone camera"
        if self.name.lower().startswith(prefix.lower()):
            return self.name
        return f"{prefix} - {self.name}"

    @field_validator("latitude")
    @classmethod
    def _lat_in_india(cls, v):
        if not (INDIA_BBOX["min_lat"] <= v <= INDIA_BBOX["max_lat"]):
            raise ValueError(f"latitude {v} is outside the India bounding box -- refusing to register this camera")
        return v

    @field_validator("longitude")
    @classmethod
    def _lng_in_india(cls, v):
        if not (INDIA_BBOX["min_lng"] <= v <= INDIA_BBOX["max_lng"]):
            raise ValueError(f"longitude {v} is outside the India bounding box -- refusing to register this camera")
        return v

    @field_validator("stream_source")
    @classmethod
    def _no_credentials_in_file(cls, v):
        # Catches the common accident of pasting a real rtsp://user:pass@host
        # URL straight into the checked-in config file.
        if re.search(r"rtsp://[^/@]+:[^/@]+@", v):
            raise ValueError(
                "stream_source appears to contain embedded RTSP credentials -- "
                "use an env-var placeholder (e.g. 'env:CAM_RTSP_URL') instead, "
                "credentials must never be committed to config/cameras.json"
            )
        return v


_camera_registry: dict[str, Camera] = {}


def load_cameras(path: Path = CAMERAS_CONFIG_PATH) -> dict[str, Camera]:
    """Loads and validates config/cameras.json. Invalid entries are
    skipped with a printed warning, never silently substituted with a
    default camera."""
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
            print(f"camera registry: skipping invalid entry {entry.get('camera_id', '?')}: {e}")
    _camera_registry = registry
    return _camera_registry


def get_camera(camera_id: str) -> Optional[Camera]:
    if not _camera_registry:
        load_cameras()
    return _camera_registry.get(camera_id)


def all_cameras() -> list[Camera]:
    if not _camera_registry:
        load_cameras()
    return list(_camera_registry.values())


def resolve_stream_source(camera: Camera) -> str:
    """Resolves a stream_source that references an env var (e.g.
    'env:CAM3_RTSP_URL') to its real value at connect time. Never logs
    the resolved value -- only the env var NAME may be logged/printed,
    since the resolved value may contain credentials."""
    if camera.stream_source.startswith("env:"):
        import os
        var_name = camera.stream_source[len("env:"):]
        value = os.environ.get(var_name)
        if not value:
            raise ValueError(f"camera {camera.camera_id}: env var {var_name} is not set")
        return value
    return camera.stream_source


# Load at import time so the registry is populated before the first request.
load_cameras()
