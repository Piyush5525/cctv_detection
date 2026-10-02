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
from api.services import audit
from api.services.demo_trigger import DemoUnavailable, trigger_demo_incident

router = APIRouter(prefix="/cameras", tags=["cameras"])
demo_router = APIRouter(prefix="/demo", tags=["demo"], dependencies=[Depends(require_demo_token)])


@router.get("")
async def list_cameras():
    """Registered phone cameras (the real, added cameras) for the demo trigger picker; no stream sources or coordinates."""
    from api.models.camera import all_cameras
    return {"cameras": [{"camera_id": c.camera_id, "name": c.display_name, "camera_type": c.camera_type,
                         "location_basis": c.location_basis, "place_text": c.place_text} for c in sorted((c for c in all_cameras() if c.enabled and c.camera_type == "phone"), key=lambda c: c.camera_id)]}


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
    except DemoUnavailable as exc: raise HTTPException(409, str(exc))   # clip missing / detector did not fire: said plainly, nothing forced
    except ValueError as exc: raise HTTPException(422, str(exc))
    except RuntimeError as exc: raise HTTPException(503, str(exc))


class DetectorToggle(BaseModel):
    camera_id: str
    detector: str
    enabled: bool


@demo_router.post("/detectors")
async def toggle_detector(payload: DetectorToggle):
    """Runtime per-camera detector toggle (no restart). Audited."""
    from api.models.camera import KNOWN_DETECTORS
    if payload.detector not in KNOWN_DETECTORS: raise HTTPException(422, f"unknown detector {payload.detector!r}")
    if payload.camera_id not in camera_workers.workers: raise HTTPException(409, "that camera has no running worker (offline or workers disabled)")
    try: applied = await asyncio.to_thread(camera_workers.set_camera_detector, payload.camera_id, payload.detector, payload.enabled)
    except RuntimeError as exc: raise HTTPException(503, str(exc))
    audit.record("detector_toggle", f"{payload.camera_id}: {payload.detector} {'on' if payload.enabled else 'off'} -> {','.join(applied) or 'none'}")
    return {"camera_id": payload.camera_id, "detectors": applied}


class DryRun(BaseModel):
    enabled: bool


class ScriptedAutoCall(BaseModel):
    enabled: bool


@demo_router.post("/scripted-auto-call")
async def set_scripted_auto_call(payload: ScriptedAutoCall):
    """"Scripted incidents: call after delay". Only has an effect while DEMO_MODE is true; every call safety rule still applies. Audited."""
    settings.SCRIPTED_AUTO_CALL = payload.enabled
    audit.record("scripted_auto_call", "on" if payload.enabled else "off")
    return {"scripted_auto_call": settings.SCRIPTED_AUTO_CALL, "effective": settings.SCRIPTED_AUTO_CALL and settings.DEMO_MODE}


class AlertsToggle(BaseModel):
    enabled: bool


@demo_router.post("/alerts")
async def set_alerts(payload: AlertsToggle):
    """Runtime ALERTS_ENABLED (the master gate for every outbound Telegram message and call). Same effect as the env var, lost on
    restart. The allowlist, hard-blocked numbers, DEMO_MODE, DRY RUN, cooldowns and the call cap all still apply. Audited."""
    settings.ALERTS_ENABLED = payload.enabled
    audit.record("alerts", "on (real Telegram/calls allowed)" if payload.enabled else "off")
    return {"alerts_enabled": settings.ALERTS_ENABLED}


@demo_router.post("/dry-run")
async def set_dry_run(payload: DryRun):
    """DRY RUN: Telegram stays real, calls are suppressed. Runtime flag; audited."""
    settings.DEMO_DRY_RUN = payload.enabled
    audit.record("dry_run", "on" if payload.enabled else "off")
    return {"dry_run": settings.DEMO_DRY_RUN}


@demo_router.post("/reset")
async def reset_demo():
    from api.services import demo_reset
    audit.record("demo_reset", "incidents cleared (DB backed up first)")
    return await asyncio.to_thread(demo_reset.reset, False)


@demo_router.post("/showcase")
async def load_showcase():
    from api.services import demo_reset
    audit.record("demo_showcase", "showcase loaded (DB backed up first)")
    try: return await asyncio.to_thread(demo_reset.reset, True)
    except demo_reset.ShowcaseMissing as exc: raise HTTPException(404, str(exc))
