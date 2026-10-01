"""DEV/TEST-ONLY upload-and-detect endpoint (CHANGELOG.md "CCTV Incident
Capture Pipeline" phase, Part 1 item 2). The product is CCTV-only: this
endpoint no longer accepts a location from the request (that was the
exact kind of "location from upload time, not capture time" problem an
earlier phase's addendum tried to fix, before the product was narrowed
to CCTV-only and that whole mobile/upload provenance model was
cancelled). It now requires a real registered camera_id and takes that
camera's registry location; every incident it creates is marked
source="test_replay", never "live" -- this is a way to manually test
the detection models against an arbitrary photo/video, not a real
ingestion path. The real live-capture path is main.py's camera loop.
"""

import tempfile
from pathlib import Path

import cv2
import numpy as np
from fastapi import APIRouter, UploadFile, File, Form, HTTPException

from api.services.detection_service import (
    detect_and_create_incident, detect_video_and_create_incidents, _make_json_serializable,
)
from api.models.camera import get_camera

router = APIRouter(prefix="/detect", tags=["detect"])

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}


@router.post("")
async def detect_media(
    file: UploadFile = File(...),
    camera_id: str = Form(...),
    min_confidence: float = Form(0.3),
):
    cam = get_camera(camera_id)
    if cam is None:
        raise HTTPException(
            status_code=422,
            detail=f"camera_id {camera_id!r} is not a registered camera (config/cameras.json). "
                   f"This dev/test endpoint requires a real registered camera_id -- it no longer "
                   f"accepts a location from the request.",
        )
    location_name = cam.place_text
    latitude = cam.latitude
    longitude = cam.longitude

    suffix = Path(file.filename or "").suffix.lower()
    raw_bytes = await file.read()
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Empty file upload")

    if suffix in IMAGE_EXTENSIONS:
        buffer = np.frombuffer(raw_bytes, dtype=np.uint8)
        frame = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
        if frame is None:
            raise HTTPException(status_code=400, detail="Could not decode image file")

        report = await detect_and_create_incident(
            frame_bgr=frame,
            camera_id=camera_id,
            location_name=location_name,
            latitude=latitude,
            longitude=longitude,
            min_confidence=min_confidence,
        )
        # model_results embeds raw YOLO output (numpy boxes/scalars) even
        # when no incident is created -- serialize the whole report once
        # here rather than patch every return site inside the service.
        return _make_json_serializable(report)

    if suffix in VIDEO_EXTENSIONS:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(raw_bytes)
            tmp_path = Path(tmp.name)

        try:
            report = await detect_video_and_create_incidents(
                video_path=tmp_path,
                raw_video_bytes=raw_bytes,
                camera_id=camera_id,
                location_name=location_name,
                latitude=latitude,
                longitude=longitude,
                min_confidence=min_confidence,
            )
            return _make_json_serializable(report)
        finally:
            tmp_path.unlink(missing_ok=True)

    raise HTTPException(
        status_code=400,
        detail=f"Unsupported file type '{suffix}'. Use an image ({', '.join(IMAGE_EXTENSIONS)}) or video ({', '.join(VIDEO_EXTENSIONS)}).",
    )
