"""ARCHIVED, NOT PART OF THE LIVE PRODUCT -- see CHANGELOG.md "CCTV
Incident Capture Pipeline / Scope Reset" phase.

The live product is CCTV-only (api/models/incident_v2.py). The
following features defined in this module are CANCELLED and will not
be implemented:
  - SourceType.MOBILE_DEVICE, SourceType.UPLOAD
  - LocationSource.DEVICE_GPS, LocationSource.MEDIA_METADATA,
    LocationSource.MANUAL_PIN
  - device_id field
  - location_accuracy_m, low_accuracy, flagged_suspicious_location
  - track: List[TrackPoint]
  - validate_source_provenance() mobile_device branch

This module is kept (not deleted) only because
archive/news_scrape_incidents.json and the v1 incident model
(api/models/incident.py) still reference its shapes for historical
data. No live code path imports from here.

Original docstring:
Source-type and location-provenance fields, shared by every incident
regardless of where it came from (fixed CCTV, a phone/dashcam/bodycam
upload, or a news scrape). The core rule this file encodes: an
incident's location must come from whatever actually captured it, at
capture time -- never from the server, never from a default/fallback
coordinate, and the caller must be honest about how confident that
location really is (location_source + location_verified +
location_accuracy_m).
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator

MAX_ACCURACY_M = 200.0  # config value: GPS accuracy worse than this needs low_accuracy=true
MAX_CAPTURE_AGE_DAYS = 365 * 5  # a captured_at older than this is implausible for a live system, not just "stale news"
SUSPICIOUS_REPEATED_COORD_ROUND = 4  # decimal places; used by callers to detect repeated-suspiciously coordinates


class SourceType(str, Enum):
    FIXED_CCTV = "fixed_cctv"
    MOBILE_DEVICE = "mobile_device"
    UPLOAD = "upload"
    NEWS_SCRAPE = "news_scrape"


class LocationSource(str, Enum):
    CAMERA_REGISTRY = "camera_registry"
    DEVICE_GPS = "device_gps"
    MEDIA_METADATA = "media_metadata"
    MANUAL_PIN = "manual_pin"
    GEOCODED_TEXT = "geocoded_text"
    UNKNOWN = "unknown"


class EvidenceType(str, Enum):
    IMAGE = "image"
    VIDEO = "video"


class TrackPoint(BaseModel):
    """One point in a simplified moving-video track (e.g. dashcam)."""
    latitude: float
    longitude: float
    t_offset_s: float = Field(ge=0, description="seconds since the clip's start_timestamp")


class Evidence(BaseModel):
    type: EvidenceType
    path: str
    thumbnail_path: Optional[str] = None
    duration_s: Optional[float] = None  # null for images
    width: Optional[int] = None
    height: Optional[int] = None


class LocationProvenance(BaseModel):
    source_type: SourceType
    location_source: LocationSource = LocationSource.UNKNOWN
    location_accuracy_m: Optional[float] = None
    location_verified: bool = False
    device_id: Optional[str] = None  # opaque per-device token; NEVER returned by public endpoints
    captured_at: Optional[datetime] = None  # from the device/media at capture time
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    low_accuracy: bool = False
    flagged_suspicious_location: bool = False
    track: list[TrackPoint] = Field(default_factory=list, max_length=50)

    @field_validator("captured_at")
    @classmethod
    def _captured_at_not_future_not_ancient(cls, v):
        if v is None:
            return v
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if v > now:
            raise ValueError(f"captured_at {v.isoformat()} is in the future")
        age_days = (now - v).days
        if age_days > MAX_CAPTURE_AGE_DAYS:
            raise ValueError(f"captured_at {v.isoformat()} is implausibly old ({age_days} days)")
        return v


def validate_source_provenance(
    source_type: SourceType,
    camera_id: Optional[str],
    latitude: Optional[float],
    longitude: Optional[float],
    location_source: LocationSource,
    location_accuracy_m: Optional[float],
    captured_at: Optional[datetime],
) -> Optional[str]:
    """Returns an error message if the combination is invalid for the given
    source_type (caller should quarantine, not silently accept), or None if
    valid. This is the single place the per-source-type validation rules
    live, so api/routes/detect.py and any future ingestion path apply the
    same rules.
    """
    if source_type == SourceType.FIXED_CCTV:
        if not camera_id:
            return "fixed_cctv incidents must have a camera_id"
        if location_source != LocationSource.CAMERA_REGISTRY:
            return "fixed_cctv incidents must have location_source=camera_registry"
    elif source_type == SourceType.MOBILE_DEVICE:
        if latitude is None or longitude is None:
            return "mobile_device incidents must have coordinates"
        if location_accuracy_m is None:
            return "mobile_device incidents must have accuracy_m"
        if captured_at is None:
            return "mobile_device incidents must have captured_at"
    return None


def is_suspicious_coordinate(latitude: Optional[float], longitude: Optional[float]) -> bool:
    """Flags (does not reject) coordinates that are exactly 0,0 -- a
    classic silent-default-fallback signature, real GPS noise essentially
    never lands exactly there."""
    if latitude is None or longitude is None:
        return False
    return latitude == 0.0 and longitude == 0.0
