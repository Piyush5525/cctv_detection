from fastapi import APIRouter, HTTPException, Query

from api.services.emergency_service import nearest_emergency_services
from api.services import incident_service_v2 as svc

router = APIRouter(prefix="/emergency", tags=["emergency"])


@router.get("/nearest")
async def get_nearest_services(
    latitude: float = Query(...),
    longitude: float = Query(...),
):
    """Nearest real police stations and hospitals to a coordinate, via
    OpenStreetMap Overpass. Used to know who to contact for a given
    incident's location."""
    return nearest_emergency_services(latitude, longitude)


@router.get("/incidents/{incident_id}/nearest")
async def get_nearest_services_for_incident(incident_id: str):
    """Convenience lookup: resolves an incident's own location first, so the
    frontend doesn't need to read location off the incident itself just to
    call /emergency/nearest. Re-pointed at the CCTV-only incident store
    (CHANGELOG.md "CCTV Incident Capture Pipeline" phase) since the old
    in-memory incident_service is no longer populated by anything --
    this endpoint's own lookup logic (out of scope for that phase) is
    otherwise unchanged."""
    incident = svc.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return nearest_emergency_services(incident["latitude"], incident["longitude"])
