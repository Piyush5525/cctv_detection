"""CCTV-only incident API (CHANGELOG.md "CCTV Incident Capture Pipeline"
phase). Backed by SQLite (api/db.py) via api/services/incident_service_v2.py.
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

from api.models.incident_v2 import IncidentStatusUpdate
from api.services import incident_service_v2 as svc

router = APIRouter(prefix="/incidents", tags=["incidents"])


@router.get("")
async def list_incidents(
    camera_id: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    rows = svc.list_incidents(camera_id, category, status, source, start_date, end_date, limit, offset)
    total = len(svc.list_incidents(camera_id, category, status, source, start_date, end_date))
    return {"incidents": rows, "total": total, "limit": limit, "offset": offset}


@router.get("/{incident_id}")
async def get_incident(incident_id: str):
    data = svc.get_incident(incident_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return data


@router.patch("/{incident_id}/status")
async def update_incident_status(incident_id: str, update: IncidentStatusUpdate):
    data = svc.update_status(incident_id, update)
    if data is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return data


@router.get("/_internal/quarantine")
async def get_quarantine():
    return svc.list_quarantine()


@router.websocket("/ws")
async def incidents_websocket(websocket: WebSocket):
    await websocket.accept()
    queue = svc.subscribe()
    try:
        while True:
            incident = await queue.get()
            await websocket.send_json({"type": "incident_created", "data": incident.to_dict()})
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        svc.unsubscribe(queue)
