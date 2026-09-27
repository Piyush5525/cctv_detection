from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from pathlib import Path
import psutil
import torch
import cv2

from api.core.config import settings


router = APIRouter(prefix="/system", tags=["system"])

LIVE_FRAME_PATH = Path(__file__).resolve().parent.parent.parent / "live_frame.jpg"


class SystemHealth(BaseModel):
    status: str
    timestamp: datetime
    cpu_percent: float
    memory_percent: float
    disk_percent: float
    gpu_available: bool
    gpu_memory_used: Optional[float] = None
    gpu_memory_total: Optional[float] = None
    detection_models_loaded: dict
    uptime_seconds: float


class DetectionModelStatus(BaseModel):
    name: str
    loaded: bool
    device: str
    model_path: Optional[str] = None
    last_inference_ms: Optional[float] = None


@router.get("/health", response_model=SystemHealth)
async def get_system_health():
    cpu_percent = psutil.cpu_percent(interval=0.1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')

    gpu_available = torch.cuda.is_available()
    gpu_memory_used = None
    gpu_memory_total = None

    if gpu_available:
        gpu_memory_used = torch.cuda.memory_allocated() / 1024**3
        gpu_memory_total = torch.cuda.get_device_properties(0).total_memory / 1024**3

    detection_models = {
        "violence_clip": {"loaded": True, "device": "cpu", "model": "ViT-B/32"},
        "fall_detection": {"loaded": True, "device": "cpu", "model": "yolov8n-pose"},
        "snatch_detection": {"loaded": True, "device": "cpu", "model": "ST-GCN + CNN-LSTM"},
        "fire_detection": {"loaded": True, "device": "cpu", "model": "YOLOv8-nano"},
        "crash_detection": {"loaded": True, "device": "cpu", "model": "YOLOv8s"},
    }

    return SystemHealth(
        status="healthy",
        timestamp=datetime.utcnow(),
        cpu_percent=cpu_percent,
        memory_percent=memory.percent,
        disk_percent=disk.percent / disk.total * 100,
        gpu_available=gpu_available,
        gpu_memory_used=round(gpu_memory_used, 2) if gpu_memory_used else None,
        gpu_memory_total=round(gpu_memory_total, 2) if gpu_memory_total else None,
        detection_models_loaded=detection_models,
        uptime_seconds=0.0
    )


@router.get("/frame")
async def get_live_frame():
    try:
        data = LIVE_FRAME_PATH.read_bytes()
    except OSError:
        raise HTTPException(status_code=404, detail="No live frame available. Start the detection pipeline.")
    return Response(
        content=data,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@router.get("/status")
async def get_system_status():
    return {
        "project": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "api_version": settings.API_V1_STR,
        "evidence_clips_dir": str(settings.EVIDENCE_CLIPS_DIR),
        "jaipur_center": {
            "lat": settings.JAIPUR_CENTER_LAT,
            "lng": settings.JAIPUR_CENTER_LNG
        }
    }