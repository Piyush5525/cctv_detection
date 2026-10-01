"""ARCHIVED, NOT PART OF THE LIVE PRODUCT -- see CHANGELOG.md "CCTV
Incident Capture Pipeline / Scope Reset" phase.

The live product uses api/routes/incidents_v2.py. This v1 route
module is NOT registered in api/main.py and serves no live traffic.
Kept only because it imports from the archived v1 incident model.
"""
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from api.models.incident import (
    Incident, IncidentCreate, IncidentUpdate, IncidentFilter,
    PaginatedIncidents, IncidentType, SeverityLevel, IncidentStatus,
    Location, AnalyticsSummary, IncidentTrend, HeatmapPoint
)
from api.services.incident_service import incident_service, QuarantineError


router = APIRouter(prefix="/incidents", tags=["incidents"])


class WebSocketMessage(BaseModel):
    type: str
    data: dict


@router.get("")
async def list_incidents(
    incident_types: Optional[List[IncidentType]] = Query(None),
    severities: Optional[List[SeverityLevel]] = Query(None),
    statuses: Optional[List[IncidentStatus]] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    camera_id: Optional[str] = Query(None),
    min_confidence: Optional[float] = Query(None),
    search_query: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_by: str = Query("timestamp", pattern="^(timestamp|severity|confidence)$"),
    sort_desc: bool = Query(True)
):
    filter_params = IncidentFilter(
        incident_types=incident_types,
        severities=severities,
        statuses=statuses,
        start_date=start_date,
        end_date=end_date,
        camera_id=camera_id,
        min_confidence=min_confidence,
        search_query=search_query
    )
    result = await incident_service.list_incidents(filter_params, page, page_size, sort_by, sort_desc)
    # device_id must never appear in a public response (Phase 1b addendum) --
    # strip it per-incident rather than relying on response_model, which
    # would re-serialize the full Incident (device_id included).
    return {
        **result.model_dump(mode="json", exclude={"incidents"}),
        "incidents": [inc.to_public_dict() for inc in result.incidents],
    }


@router.get("/recent")
async def get_recent_incidents(limit: int = Query(10, ge=1, le=50)):
    incidents = await incident_service.get_recent_incidents(limit)
    return [inc.to_public_dict() for inc in incidents]


@router.get("/analytics/summary", response_model=AnalyticsSummary)
async def get_analytics_summary():
    return await incident_service.get_analytics_summary()


@router.get("/analytics/trends", response_model=List[IncidentTrend])
async def get_incident_trends(hours: int = Query(24, ge=1, le=168)):
    return await incident_service.get_incident_trends(hours)


@router.get("/analytics/heatmap", response_model=List[HeatmapPoint])
async def get_heatmap_data():
    return await incident_service.get_heatmap_data()


@router.get("/{incident_id}")
async def get_incident(incident_id: str):
    incident = await incident_service.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident.to_public_dict()


@router.post("", status_code=201)
async def create_incident(incident_data: IncidentCreate):
    try:
        incident = await incident_service.create_incident(incident_data)
    except QuarantineError as e:
        raise HTTPException(status_code=422, detail=str(e))
    # device_id is an opaque per-device token and must never appear in a
    # public API response (Phase 1b addendum) -- response_model=Incident
    # would have serialized it directly, so this route builds the response
    # from to_public_dict() instead of relying on FastAPI's response_model.
    return incident.to_public_dict()


@router.patch("/{incident_id}")
async def update_incident(incident_id: str, update_data: IncidentUpdate):
    incident = await incident_service.update_incident(incident_id, update_data)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident.to_public_dict()


@router.delete("/{incident_id}", status_code=204)
async def delete_incident(incident_id: str):
    if incident_id not in incident_service._incidents:
        raise HTTPException(status_code=404, detail="Incident not found")
    del incident_service._incidents[incident_id]
    return None


@router.websocket("/ws")
async def incidents_websocket(websocket: WebSocket):
    await websocket.accept()
    queue = incident_service.subscribe()
    try:
        while True:
            incident = await queue.get()
            await websocket.send_json({
                "type": "incident_created",
                "data": incident.to_public_dict()
            })
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        incident_service.unsubscribe(queue)