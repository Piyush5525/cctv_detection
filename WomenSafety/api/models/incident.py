"""ARCHIVED, NOT PART OF THE LIVE PRODUCT -- see CHANGELOG.md "CCTV
Incident Capture Pipeline / Scope Reset" phase.

The live product uses api/models/incident_v2.py (CCTV-only schema).
This v1 model is kept (not deleted) only because the old in-memory
incident_service.py and archive/news_scrape_incidents.json reference
its shapes. No live API route imports from this module -- api/main.py
registers incidents_v2 routes, not the old incidents routes.

Cancelled fields in this module (never to be implemented):
  source_type, location_source, location_accuracy_m, location_verified,
  device_id, low_accuracy, flagged_suspicious_location, track.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator
import uuid

from api.models.provenance import (
    SourceType, LocationSource, Evidence, TrackPoint,
)


def utcnow() -> datetime:
    """Timezone-AWARE UTC now, for use as every timestamp field's
    default_factory in this module. Plain datetime.utcnow() (used all over
    this codebase's call sites, outside this file) returns a naive datetime;
    Pydantic then serializes it with no timezone suffix (e.g.
    "2026-09-28T12:30:34"), and every browser's `new Date(...)` parses that
    as LOCAL time rather than UTC -- on a UTC+5:30 machine that silently
    shifts the timestamp 5.5 hours into the future, breaking any "time ago"
    / age display. A field_validator alone doesn't fully cover this: Pydantic
    v2 skips "before" validators on default_factory-produced values unless
    validate_default=True is set, which is why default_factory=datetime.utcnow
    slipped through even with the validator below -- so the factory itself
    must produce an aware datetime, and the validator only normalizes values
    supplied explicitly at construction (e.g. IncidentCreate.timestamp from
    an API caller still using naive datetime.utcnow())."""
    return datetime.now(timezone.utc)


class UTCTimestampModel(BaseModel):
    """Base for models with datetime fields that may be supplied as naive
    UTC (e.g. via IncidentCreate.timestamp, still built with plain
    datetime.utcnow() at call sites outside this file). Tags any naive
    datetime as UTC on the way in, without changing the moment in time it
    represents. Fields with a default should use default_factory=utcnow
    (above), not datetime.utcnow, so their default already carries tzinfo."""

    @field_validator("timestamp", "created_at", "updated_at", "resolved_at",
                      "start_timestamp", "end_timestamp", "event_time",
                      "captured_at", "received_at", mode="before", check_fields=False)
    @classmethod
    def _assume_utc_if_naive(cls, v):
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v


class IncidentType(str, Enum):
    VIOLENCE = "violence"
    FALL = "fall"
    WOMEN_SAFETY = "women_safety"
    SNATCH = "snatch"
    FIRE = "fire"
    CRASH = "crash"
    OTHER = "other"


class SeverityLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IncidentStatus(str, Enum):
    NEW = "new"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"
    FALSE_POSITIVE = "false_positive"


class Location(BaseModel):
    # Nullable, same treatment as Incident.confidence: a scraped incident
    # whose place only resolves to something too coarse to trust (e.g. a
    # whole district, not a city/town point -- see CHANGELOG.md Phase 1
    # "Amravati" example) must not be forced into a fake (0.0, 0.0) or any
    # other default coordinate. null here means "we genuinely don't know",
    # not "we know it's at the equator/prime meridian".
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    address: str
    camera_id: str = "CAM-001"


class EvidenceClip(UTCTimestampModel):
    clip_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    incident_id: str
    video_path: str
    thumbnail_path: Optional[str] = None
    duration_seconds: float = 10.0
    start_timestamp: datetime
    end_timestamp: datetime
    created_at: datetime = Field(default_factory=utcnow)


class Incident(UTCTimestampModel):
    incident_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    incident_type: IncidentType
    severity: SeverityLevel
    status: IncidentStatus = IncidentStatus.NEW
    # Nullable: a news-scraped incident has never been scored by a real CV
    # model, and storing a fake confidence value for it (as the previous
    # scraper version did, a hardcoded 0.5 for every single record) is
    # exactly the kind of silent fallback this project is trying to stop
    # doing. null here means "not scored", not "scored at zero".
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    timestamp: datetime = Field(default_factory=utcnow)
    location: Location
    detection_data: Dict[str, Any] = Field(default_factory=dict)
    evidence_clip: Optional[EvidenceClip] = None
    thumbnail_path: Optional[str] = None
    notes: str = ""
    assigned_to: Optional[str] = None
    resolved_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    # --- Camera/device addendum fields (Phase 1b) ---
    # origin distinguishes "how did this incident enter the system" at a
    # coarse level (matches detection_data.source's existing "news_scrape"
    # convention); source_type is the finer-grained capture-device
    # classification the addendum asks for. Both default to the values
    # that make every pre-addendum incident (news-scraped) remain valid
    # without modification.
    origin: str = "news_scrape"  # "camera" | "news_scrape" | "upload"
    camera_id: Optional[str] = None
    place_text: Optional[str] = None
    event_time: Optional[datetime] = None  # capture-time event moment, distinct from `timestamp` (kept for backward compat)
    evidence: Optional[Evidence] = None
    source_type: SourceType = SourceType.NEWS_SCRAPE
    location_source: LocationSource = LocationSource.GEOCODED_TEXT
    location_accuracy_m: Optional[float] = None
    location_verified: bool = False
    device_id: Optional[str] = None  # NEVER returned by public endpoints -- stripped in to_public_dict()
    captured_at: Optional[datetime] = None
    received_at: datetime = Field(default_factory=utcnow)
    low_accuracy: bool = False
    flagged_suspicious_location: bool = False
    track: List[TrackPoint] = Field(default_factory=list)

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")

    def to_public_dict(self) -> dict:
        """Same as to_dict() but with device_id stripped -- device_id is an
        opaque per-device token that must never appear in a public API
        response (addendum requirement). Use this for every response body
        a frontend/external caller sees; to_dict() remains available for
        internal/storage use."""
        d = self.model_dump(mode="json")
        d.pop("device_id", None)
        return d


class IncidentCreate(BaseModel):
    incident_type: IncidentType
    severity: SeverityLevel
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    timestamp: Optional[datetime] = None
    location: Location
    detection_data: Dict[str, Any] = Field(default_factory=dict)
    evidence_clip_path: Optional[str] = None
    thumbnail_path: Optional[str] = None

    # --- Camera/device addendum fields (Phase 1b) ---
    origin: str = "news_scrape"
    camera_id: Optional[str] = None
    place_text: Optional[str] = None
    event_time: Optional[datetime] = None
    evidence: Optional[Evidence] = None
    source_type: SourceType = SourceType.NEWS_SCRAPE
    location_source: LocationSource = LocationSource.GEOCODED_TEXT
    location_accuracy_m: Optional[float] = None
    location_verified: bool = False
    device_id: Optional[str] = None
    captured_at: Optional[datetime] = None
    low_accuracy: bool = False
    flagged_suspicious_location: bool = False
    track: List[TrackPoint] = Field(default_factory=list)


class IncidentUpdate(BaseModel):
    status: Optional[IncidentStatus] = None
    severity: Optional[SeverityLevel] = None
    notes: Optional[str] = None
    assigned_to: Optional[str] = None


class IncidentFilter(BaseModel):
    incident_types: Optional[List[IncidentType]] = None
    severities: Optional[List[SeverityLevel]] = None
    statuses: Optional[List[IncidentStatus]] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    camera_id: Optional[str] = None
    min_confidence: Optional[float] = None
    search_query: Optional[str] = None


class PaginatedIncidents(BaseModel):
    incidents: List[Incident]
    total: int
    page: int
    page_size: int
    total_pages: int


class AnalyticsSummary(BaseModel):
    total_incidents: int
    active_incidents: int
    critical_incidents: int
    resolved_today: int
    detection_accuracy: float
    avg_response_time_seconds: float


class IncidentTrend(BaseModel):
    period: str
    count: int
    by_type: Dict[str, int]
    by_severity: Dict[str, int]


class HeatmapPoint(BaseModel):
    latitude: float
    longitude: float
    weight: float
    incident_type: IncidentType