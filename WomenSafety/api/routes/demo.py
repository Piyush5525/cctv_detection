"""GET /api/v1/demo-state: read-only state the Demo panel and the header need (no token: it carries no secrets, URLs,
phone numbers or coordinates). The state-changing demo routes (trigger, reset, detector toggles, dry run) stay behind
X-Demo-Token in api/routes/cameras.py."""
from fastapi import APIRouter

from api.core.config import settings
from api.models.camera import all_cameras
from api.services import audit, demo_clips
from api.services.camera_workers import camera_workers

router = APIRouter(prefix="/demo-state", tags=["demo"])


@router.get("")
async def demo_state():
    cams = []
    for c in sorted((c for c in all_cameras() if c.enabled and c.camera_type == "phone"), key=lambda c: c.camera_id):
        worker = camera_workers.workers.get(c.camera_id)
        cams.append({"camera_id": c.camera_id, "name": c.display_name, "running": worker is not None,
                     "detectors": list(worker.detectors) if worker is not None else c.active_detectors,
                     "defaults": c.active_detectors})
    return {"demo_mode": settings.DEMO_MODE, "dry_run": settings.DEMO_DRY_RUN,
            "scripted_auto_call": settings.SCRIPTED_AUTO_CALL, "scripted_auto_call_effective": settings.SCRIPTED_AUTO_CALL and settings.DEMO_MODE,
            "escalation_delay_s": settings.DEMO_ESCALATION_DELAY_S, "categories": demo_clips.categories(),
            "cameras": cams, "all_detectors": ["fire", "crash", "fall", "violence", "snatch"], "audit": audit.entries(20)}
