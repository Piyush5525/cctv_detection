from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
import uuid


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
    latitude: float
    longitude: float
    address: str
    camera_id: str = "CAM-001"


class EvidenceClip(BaseModel):
    clip_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    incident_id: str
    video_path: str
    thumbnail_path: Optional[str] = None
    duration_seconds: float = 10.0
    start_timestamp: datetime
    end_timestamp: datetime
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Incident(BaseModel):
    incident_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    incident_type: IncidentType
    severity: SeverityLevel
    status: IncidentStatus = IncidentStatus.NEW
    confidence: float = Field(ge=0.0, le=1.0)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    location: Location
    detection_data: Dict[str, Any] = Field(default_factory=dict)
    evidence_clip: Optional[EvidenceClip] = None
    thumbnail_path: Optional[str] = None
    notes: str = ""
    assigned_to: Optional[str] = None
    resolved_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")


class IncidentCreate(BaseModel):
    incident_type: IncidentType
    severity: SeverityLevel
    confidence: float = Field(ge=0.0, le=1.0)
    timestamp: Optional[datetime] = None
    location: Location
    detection_data: Dict[str, Any] = Field(default_factory=dict)
    evidence_clip_path: Optional[str] = None
    thumbnail_path: Optional[str] = None


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