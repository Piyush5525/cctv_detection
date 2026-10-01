"""GET /api/v1/map/groups -- incidents grouped by camera_id for map
display (CHANGELOG.md "CCTV Incident Capture Pipeline" phase). This is
data-shaping only; NO frontend map rendering work happens in this
phase (explicitly deferred to Phase 3).

The product is CCTV-only: mobile-device/upload proximity clustering and
the news_scrape group were removed along with that cancelled feature
set (see CHANGELOG.md "Scope reset"). Grouping is strictly by
camera_id -- two cameras that happen to be geographically close stay in
separate groups because they ARE separate cameras, never merged by
coordinate proximity.
"""
from typing import Optional

from fastapi import APIRouter, Query

from api.models.camera import get_camera
from api.services.phone_location import location_fields, resolve_location
from api.services import incident_service_v2 as svc

router = APIRouter(prefix="/map", tags=["map"])


@router.get("/groups")
async def get_map_groups(
    category: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    limit_per_group: int = Query(10, ge=1, le=100),
    offset_per_group: int = Query(0, ge=0),
):
    all_incidents = svc.list_incidents(category=category, status=status, source=source,
                                        start_date=start_date, end_date=end_date)

    by_camera: dict[str, list] = {}
    for inc in all_incidents:
        by_camera.setdefault(inc["camera_id"], []).append(inc)

    groups = []
    for camera_id, members in by_camera.items():
        members.sort(key=lambda i: i["event_start"], reverse=True)
        cam = get_camera(camera_id)
        loc = resolve_location(cam) if cam else None  # smoothed device position for phones when mode != fixed
        page = members[offset_per_group:offset_per_group + limit_per_group]
        groups.append({
            "camera_id": camera_id,
            "camera_name": cam.display_name if cam else members[0]["camera_name"],
            "camera_type": cam.camera_type if cam else "cctv",
            "location_basis": cam.location_basis if cam else "simulated_placement",
            "place_text": cam.place_text if cam else members[0]["place_text"],
            "latitude": loc.lat if loc else members[0]["latitude"],
            "longitude": loc.lon if loc else members[0]["longitude"],
            **(location_fields(cam, loc) if cam else {}),
            "count": len(members),
            "latest_event_time": members[0]["event_start"],
            "incidents": [
                {
                    "incident_id": i["incident_id"],
                    "category": i["category"],
                    "event_start": i["event_start"],
                    "thumbnail_url": f"/api/v1/evidence/v2/{i['camera_id']}/"
                                      f"{i['event_start'][:10]}/{i['incident_id']}/thumbnail.jpg",
                    "peak_confidence": i["detection"]["peak_confidence"],
                    "status": i["status"],
                }
                for i in page
            ],
        })

    groups.sort(key=lambda g: g["latest_event_time"], reverse=True)
    return {"groups": groups}
