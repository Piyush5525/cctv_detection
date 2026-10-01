from fastapi import APIRouter, HTTPException, Query

from api.models.camera import get_camera
from api.services.nearby_services import NearbyServicesError, get_nearby_services

router = APIRouter(prefix="/cameras", tags=["nearby-services"])


@router.get("/{camera_id}/nearby-services")
async def nearby_services(camera_id: str, force_refresh: bool = Query(False)):
    """Lookup-only nearby hospital, police, and fire data for a registered camera.

    Returned phone fields are informational.  This endpoint never makes calls.
    """
    camera = get_camera(camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    if camera.latitude is None or camera.longitude is None:
        raise HTTPException(status_code=503, detail=f"camera location unavailable: {camera.location_error}")
    try:
        return get_nearby_services(
            camera.camera_id, camera.latitude, camera.longitude, camera.place_text,
            force_refresh=force_refresh,
        )
    except NearbyServicesError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
