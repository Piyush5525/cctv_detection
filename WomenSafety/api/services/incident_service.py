import asyncio
import random
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from collections import deque
import uuid
import json
from pathlib import Path

from api.models.incident import (
    Incident, IncidentCreate, IncidentUpdate, IncidentFilter,
    PaginatedIncidents, IncidentType, SeverityLevel, IncidentStatus,
    Location, EvidenceClip, AnalyticsSummary, IncidentTrend, HeatmapPoint
)
from api.core.config import settings


class IncidentService:
    def __init__(self):
        self._incidents: Dict[str, Incident] = {}
        self._incident_order: deque = deque(maxlen=10000)
        self._subscribers: List[asyncio.Queue] = []
        self._initialized = False
        self._dummy_locations = [
            Location(latitude=26.9124, longitude=75.7873, address="MI Road, Jaipur", camera_id="CAM-001"),
            Location(latitude=26.9150, longitude=75.7920, address="C-Scheme, Jaipur", camera_id="CAM-002"),
            Location(latitude=26.9200, longitude=75.7850, address="Bani Park, Jaipur", camera_id="CAM-003"),
            Location(latitude=26.8950, longitude=75.8000, address="Malviya Nagar, Jaipur", camera_id="CAM-004"),
            Location(latitude=26.9300, longitude=75.7700, address="Vaishali Nagar, Jaipur", camera_id="CAM-005"),
            Location(latitude=26.8800, longitude=75.8100, address="Sanganer, Jaipur", camera_id="CAM-006"),
            Location(latitude=26.9500, longitude=75.7600, address="Vidhyadhar Nagar, Jaipur", camera_id="CAM-007"),
            Location(latitude=26.8700, longitude=75.7950, address="Mansarovar, Jaipur", camera_id="CAM-008"),
        ]

    async def initialize(self):
        if self._initialized:
            return
        await self._generate_dummy_incidents(50)
        self._initialized = True

    async def _generate_dummy_incidents(self, count: int):
        incident_types = list(IncidentType)
        severities = list(SeverityLevel)
        statuses = list(IncidentStatus)

        base_time = datetime.utcnow() - timedelta(days=7)

        for i in range(count):
            incident_type = random.choice(incident_types)
            severity = random.choices(
                severities,
                weights=[0.1, 0.3, 0.4, 0.2]
            )[0]

            status = random.choices(
                statuses,
                weights=[0.3, 0.2, 0.4, 0.1]
            )[0]

            timestamp = base_time + timedelta(
                minutes=random.randint(0, 7 * 24 * 60)
            )

            location = random.choice(self._dummy_locations)

            confidence = round(random.uniform(0.55, 0.98), 2)

            detection_data = {
                "model": "yolov8" if incident_type in [IncidentType.FIRE, IncidentType.CRASH] else "clip",
                "raw_predictions": {
                    incident_type.value: confidence,
                    "normal": round(1 - confidence, 2)
                }
            }

            if incident_type == IncidentType.FALL:
                detection_data["pose_keypoints"] = True
                detection_data["track_id"] = random.randint(1, 50)
            elif incident_type == IncidentType.SNATCH:
                detection_data["vote_score"] = round(random.uniform(0.6, 0.95), 2)
                detection_data["motion_score"] = round(random.uniform(0.5, 0.9), 2)

            incident = Incident(
                incident_type=incident_type,
                severity=severity,
                status=status,
                confidence=confidence,
                timestamp=timestamp,
                location=location,
                detection_data=detection_data,
                notes="" if status != IncidentStatus.RESOLVED else "Resolved by patrol unit",
                assigned_to=f"Officer {random.randint(1, 10)}" if status == IncidentStatus.INVESTIGATING else None,
                resolved_at=timestamp + timedelta(minutes=random.randint(5, 120)) if status == IncidentStatus.RESOLVED else None,
            )

            self._incidents[incident.incident_id] = incident
            self._incident_order.appendleft(incident.incident_id)

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
        incident = Incident(
            incident_type=create_data.incident_type,
            severity=create_data.severity,
            confidence=create_data.confidence,
            timestamp=create_data.timestamp or datetime.utcnow(),
            location=create_data.location,
            detection_data=create_data.detection_data,
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
                incidents = [i for i in incidents if i.confidence >= filter_params.min_confidence]
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
            incidents.sort(key=lambda x: x.confidence, reverse=reverse)

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

        return AnalyticsSummary(
            total_incidents=total,
            active_incidents=active,
            critical_incidents=critical,
            resolved_today=resolved_today,
            detection_accuracy=round(random.uniform(0.87, 0.95), 2),
            avg_response_time_seconds=round(random.uniform(45, 180), 1)
        )

    async def get_incident_trends(self, hours: int = 24) -> List[IncidentTrend]:
        incidents = list(self._incidents.values())
        now = datetime.utcnow()
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
            weight = 1.0
            if inc.severity == SeverityLevel.CRITICAL:
                weight = 3.0
            elif inc.severity == SeverityLevel.HIGH:
                weight = 2.0
            elif inc.severity == SeverityLevel.MEDIUM:
                weight = 1.5

            points.append(HeatmapPoint(
                latitude=inc.location.latitude + random.uniform(-0.002, 0.002),
                longitude=inc.location.longitude + random.uniform(-0.002, 0.002),
                weight=weight,
                incident_type=inc.incident_type
            ))
        return points

    async def get_recent_incidents(self, limit: int = 10) -> List[Incident]:
        incident_ids = list(self._incident_order)[:limit]
        return [self._incidents[iid] for iid in incident_ids if iid in self._incidents]


incident_service = IncidentService()