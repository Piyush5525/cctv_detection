"""ARCHIVED, NOT PART OF THE LIVE PRODUCT -- see CHANGELOG.md "CCTV
Incident Capture Pipeline / Scope Reset" phase.

The live product uses api/services/incident_service_v2.py (SQLite-
backed). This in-memory service is kept (not deleted) only because the
old v1 routes (api/routes/incidents.py, also archived) import from it.
No live API route uses this service -- api/main.py registers
incidents_v2 routes, not the old incidents routes.
"""
import asyncio
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from collections import deque
import uuid
import json
from pathlib import Path

from api.models.incident import (
    Incident, IncidentCreate, IncidentUpdate, IncidentFilter,
    PaginatedIncidents, SeverityLevel, IncidentStatus,
    EvidenceClip, AnalyticsSummary, IncidentTrend, HeatmapPoint,
    utcnow,
)
from api.models.provenance import (
    SourceType, LocationSource, validate_source_provenance, is_suspicious_coordinate,
    MAX_ACCURACY_M,
)
from api.models.camera import get_camera
from api.core.config import settings


class QuarantineError(ValueError):
    """Raised when an IncidentCreate fails source-type/location-provenance
    validation (api/models/provenance.py) -- the caller (a route handler)
    should return this as a 422, never silently coerce the record into a
    valid shape by substituting a default."""
    pass


class IncidentService:
    def __init__(self):
        self._incidents: Dict[str, Incident] = {}
        self._incident_order: deque = deque(maxlen=10000)
        self._subscribers: List[asyncio.Queue] = []
        self._initialized = False

    async def initialize(self):
        if self._initialized:
            return
        # Dummy data generation removed -- the dashboard now only ever shows
        # incidents created by a real detection (POST /api/v1/detect or a
        # live camera loop via main.py), a real news scrape, or a real
        # camera/device upload. No dummy/default coordinate list is kept
        # anywhere, including as an unused fallback -- see CHANGELOG.md
        # Phase 1b for the audit that removed the last one.
        self._initialized = True

    def subscribe(self) -> asyncio.Queue:
        queue = asyncio.Queue()
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue):
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    async def _notify_subscribers(self, incident: Incident):
        for queue in self._subscribers:
            try:
                queue.put_nowait(incident)
            except asyncio.QueueFull:
                pass

    async def create_incident(self, create_data: IncidentCreate) -> Incident:
        location = create_data.location
        camera_id = create_data.camera_id or (location.camera_id if location else None)
        place_text = create_data.place_text

        # Fixed-CCTV incidents snapshot the camera's registered name and
        # coordinates onto the incident AT CREATION TIME -- if the camera
        # registry entry is edited or removed later, already-created
        # incidents keep the location they actually had when captured,
        # rather than silently changing history.
        if create_data.source_type == SourceType.FIXED_CCTV:
            cam = get_camera(camera_id) if camera_id else None
            if cam is None:
                raise QuarantineError(f"fixed_cctv incident references unknown camera_id {camera_id!r}")
            location = location.model_copy(update={
                "latitude": cam.latitude, "longitude": cam.longitude,
                "address": cam.place_text, "camera_id": cam.camera_id,
            })
            place_text = place_text or cam.place_text

        validation_error = validate_source_provenance(
            source_type=create_data.source_type,
            camera_id=camera_id,
            latitude=location.latitude if location else None,
            longitude=location.longitude if location else None,
            location_source=create_data.location_source,
            location_accuracy_m=create_data.location_accuracy_m,
            captured_at=create_data.captured_at,
        )
        if validation_error:
            raise QuarantineError(validation_error)

        low_accuracy = create_data.low_accuracy
        if (create_data.location_accuracy_m is not None
                and create_data.location_accuracy_m > MAX_ACCURACY_M
                and not low_accuracy):
            raise QuarantineError(
                f"location_accuracy_m={create_data.location_accuracy_m} exceeds MAX_ACCURACY_M="
                f"{MAX_ACCURACY_M}; set low_accuracy=true to accept it anyway"
            )

        flagged_suspicious = is_suspicious_coordinate(
            location.latitude if location else None,
            location.longitude if location else None,
        )

        incident = Incident(
            incident_type=create_data.incident_type,
            severity=create_data.severity,
            confidence=create_data.confidence,
            timestamp=create_data.timestamp or datetime.utcnow(),
            location=location,
            detection_data=create_data.detection_data,
            origin=create_data.origin,
            camera_id=camera_id,
            place_text=place_text,
            event_time=create_data.captured_at or create_data.event_time,
            evidence=create_data.evidence,
            source_type=create_data.source_type,
            location_source=(
                LocationSource.CAMERA_REGISTRY if create_data.source_type == SourceType.FIXED_CCTV
                else create_data.location_source
            ),
            location_accuracy_m=create_data.location_accuracy_m,
            location_verified=(create_data.location_verified or create_data.source_type == SourceType.FIXED_CCTV),
            device_id=create_data.device_id,
            captured_at=create_data.captured_at,
            low_accuracy=low_accuracy,
            flagged_suspicious_location=flagged_suspicious,
            track=create_data.track,
        )

        if create_data.evidence_clip_path:
            incident.evidence_clip = EvidenceClip(
                incident_id=incident.incident_id,
                video_path=create_data.evidence_clip_path,
                start_timestamp=incident.timestamp - timedelta(seconds=5),
                end_timestamp=incident.timestamp + timedelta(seconds=5),
            )

        if create_data.thumbnail_path:
            incident.thumbnail_path = create_data.thumbnail_path

        self._incidents[incident.incident_id] = incident
        self._incident_order.appendleft(incident.incident_id)

        await self._notify_subscribers(incident)
        return incident

    async def get_incident(self, incident_id: str) -> Optional[Incident]:
        return self._incidents.get(incident_id)

    async def get_all_incidents(self) -> List[Incident]:
        return list(self._incidents.values())

    async def update_incident(self, incident_id: str, update_data: IncidentUpdate) -> Optional[Incident]:
        incident = self._incidents.get(incident_id)
        if not incident:
            return None

        if update_data.status is not None:
            incident.status = update_data.status
            if update_data.status == IncidentStatus.RESOLVED:
                incident.resolved_at = datetime.utcnow()

        if update_data.severity is not None:
            incident.severity = update_data.severity

        if update_data.notes is not None:
            incident.notes = update_data.notes

        if update_data.assigned_to is not None:
            incident.assigned_to = update_data.assigned_to

        incident.updated_at = datetime.utcnow()
        await self._notify_subscribers(incident)
        return incident

    async def list_incidents(
        self,
        filter_params: Optional[IncidentFilter] = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "timestamp",
        sort_desc: bool = True
    ) -> PaginatedIncidents:
        incidents = list(self._incidents.values())

        if filter_params:
            if filter_params.incident_types:
                incidents = [i for i in incidents if i.incident_type in filter_params.incident_types]
            if filter_params.severities:
                incidents = [i for i in incidents if i.severity in filter_params.severities]
            if filter_params.statuses:
                incidents = [i for i in incidents if i.status in filter_params.statuses]
            if filter_params.start_date:
                incidents = [i for i in incidents if i.timestamp >= filter_params.start_date]
            if filter_params.end_date:
                incidents = [i for i in incidents if i.timestamp <= filter_params.end_date]
            if filter_params.camera_id:
                incidents = [i for i in incidents if i.location.camera_id == filter_params.camera_id]
            if filter_params.min_confidence:
                # Unscored (confidence=None) incidents can't meet a minimum
                # confidence threshold that was never evaluated against
                # them -- excluded, not silently treated as passing or as 0.
                incidents = [
                    i for i in incidents
                    if i.confidence is not None and i.confidence >= filter_params.min_confidence
                ]
            if filter_params.search_query:
                query = filter_params.search_query.lower()
                incidents = [
                    i for i in incidents
                    if query in i.incident_type.value.lower()
                    or query in i.location.address.lower()
                    or query in i.notes.lower()
                ]

        reverse = sort_desc
        if sort_by == "timestamp":
            incidents.sort(key=lambda x: x.timestamp, reverse=reverse)
        elif sort_by == "severity":
            severity_order = {SeverityLevel.CRITICAL: 4, SeverityLevel.HIGH: 3, SeverityLevel.MEDIUM: 2, SeverityLevel.LOW: 1}
            incidents.sort(key=lambda x: severity_order.get(x.severity, 0), reverse=reverse)
        elif sort_by == "confidence":
            # None (unscored) sorts as lowest regardless of direction, so a
            # None-vs-float comparison never happens -- Python 3 raises
            # TypeError comparing NoneType to float directly.
            incidents.sort(key=lambda x: (x.confidence is not None, x.confidence), reverse=reverse)

        total = len(incidents)
        total_pages = (total + page_size - 1) // page_size
        start = (page - 1) * page_size
        end = start + page_size
        paginated = incidents[start:end]

        return PaginatedIncidents(
            incidents=paginated,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages
        )

    async def get_analytics_summary(self) -> AnalyticsSummary:
        incidents = list(self._incidents.values())
        today = datetime.utcnow().date()

        total = len(incidents)
        active = len([i for i in incidents if i.status in [IncidentStatus.NEW, IncidentStatus.INVESTIGATING]])
        critical = len([i for i in incidents if i.severity == SeverityLevel.CRITICAL])
        resolved_today = len([i for i in incidents if i.resolved_at and i.resolved_at.date() == today])

        # Real average model confidence across all incidents actually
        # created by a detector -- there's no operator confirm/reject
        # feedback loop yet, so this isn't literal "accuracy" (which needs
        # labeled ground truth), just an honest confidence figure. The API
        # field name stays for backwards compatibility; the frontend labels
        # it "Avg Confidence". News-scraped incidents carry confidence=null
        # (never scored by a real model) and are excluded from this average
        # rather than treated as 0 -- averaging in a fake zero would silently
        # drag down a number that's supposed to mean something real.
        scored_confidences = [i.confidence for i in incidents if i.confidence is not None]
        avg_confidence = round(sum(scored_confidences) / len(scored_confidences), 2) if scored_confidences else 0.0

        resolved = [i for i in incidents if i.resolved_at]
        avg_response_seconds = (
            round(sum((i.resolved_at - i.timestamp).total_seconds() for i in resolved) / len(resolved), 1)
            if resolved else 0.0
        )

        return AnalyticsSummary(
            total_incidents=total,
            active_incidents=active,
            critical_incidents=critical,
            resolved_today=resolved_today,
            detection_accuracy=avg_confidence,
            avg_response_time_seconds=avg_response_seconds
        )

    async def get_incident_trends(self, hours: int = 24) -> List[IncidentTrend]:
        incidents = list(self._incidents.values())
        # Real incidents now carry timezone-aware UTC timestamps (see
        # api/models/incident.py's utcnow()/UTCTimestampModel) -- "now" here
        # must be aware too, or comparing it against i.timestamp below
        # raises "can't compare offset-naive and offset-aware datetimes".
        now = utcnow()
        trends = []

        for h in range(hours):
            period_start = now - timedelta(hours=h)
            period_end = period_start + timedelta(hours=1)
            period_incidents = [i for i in incidents if period_start <= i.timestamp < period_end]

            by_type = {}
            by_severity = {}
            for inc in period_incidents:
                by_type[inc.incident_type.value] = by_type.get(inc.incident_type.value, 0) + 1
                by_severity[inc.severity.value] = by_severity.get(inc.severity.value, 0) + 1

            trends.append(IncidentTrend(
                period=period_start.strftime("%H:00"),
                count=len(period_incidents),
                by_type=by_type,
                by_severity=by_severity
            ))

        return list(reversed(trends))

    async def get_heatmap_data(self) -> List[HeatmapPoint]:
        incidents = list(self._incidents.values())
        points = []
        for inc in incidents:
            # Heatmap rendering (out of this phase's scope) has no concept
            # of "unknown location" -- an incident with null coordinates
            # is simply not plottable on it, not given a fake position.
            if inc.location.latitude is None or inc.location.longitude is None:
                continue

            weight = 1.0
            if inc.severity == SeverityLevel.CRITICAL:
                weight = 3.0
            elif inc.severity == SeverityLevel.HIGH:
                weight = 2.0
            elif inc.severity == SeverityLevel.MEDIUM:
                weight = 1.5

            points.append(HeatmapPoint(
                latitude=inc.location.latitude,
                longitude=inc.location.longitude,
                weight=weight,
                incident_type=inc.incident_type
            ))
        return points

    async def get_recent_incidents(self, limit: int = 10) -> List[Incident]:
        incident_ids = list(self._incident_order)[:limit]
        return [self._incidents[iid] for iid in incident_ids if iid in self._incidents]


incident_service = IncidentService()