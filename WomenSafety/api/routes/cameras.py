import asyncio
import cv2
from fastapi import APIRouter, Depends, HTTPException
from api.core.auth import require_demo_token
from api.services.public_view import public_view
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.core.config import settings
from api.models.camera import get_camera
from api.services.camera_workers import camera_workers
from api.services.demo_trigger import trigger_demo_incident

router = APIRouter(prefix="/cameras", tags=["cameras"])
demo_router = APIRouter(prefix="/demo", tags=["demo"], dependencies=[Depends(require_demo_token)])


@router.get("")
async def list_cameras():
    """Registered cameras (for the demo trigger picker); no stream sources."""
    from api.models.camera import all_cameras
    return {"cameras": [{"camera_id": c.camera_id, "name": c.display_name, "camera_type": c.camera_type,
                         "location_basis": c.location_basis, "place_text": c.place_text} for c in sorted((c for c in all_cameras() if c.enabled), key=lambda c: (c.camera_id == "CAM-001", c.camera_id))]}


@router.get("/status")
async def status(): return camera_workers.status()


@router.get("/{camera_id}/live")
async def live(camera_id: str):
    if get_camera(camera_id) is None: raise HTTPException(404, "Camera not found")
    if camera_id not in camera_workers.workers: raise HTTPException(503, "Camera worker is not running")
    async def frames():
        while True:
            frame = camera_workers.frame(camera_id)
            if frame is not None:
                ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if ok: yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n"
            await asyncio.sleep(1 / settings.LIVE_VIEW_MAX_FPS)
    return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame")


class DemoTrigger(BaseModel):
    camera_id: str
    category: str


@demo_router.post("/trigger")
async def trigger(payload: DemoTrigger):
    if get_camera(payload.camera_id) is None: raise HTTPException(404, "Camera not found")
    try: return public_view(await asyncio.to_thread(trigger_demo_incident, payload.camera_id, payload.category))
    except ValueError as exc: raise HTTPException(422, str(exc))
    except RuntimeError as exc: raise HTTPException(503, str(exc))


@demo_router.post("/reset")
async def reset_demo():
    from api.services import demo_reset
    return await asyncio.to_thread(demo_reset.reset, False)


@demo_router.post("/showcase")
async def load_showcase():
    from api.services import demo_reset
    try: return await asyncio.to_thread(demo_reset.reset, True)
    except demo_reset.ShowcaseMissing as exc: raise HTTPException(404, str(exc))
