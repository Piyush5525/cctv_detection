import os
import json
import asyncio
import aiohttp
import threading
import time
from datetime import datetime
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict
from pathlib import Path
import cv2
import numpy as np

from api.services.evidence_service import evidence_service
from crash_detection.detector import CrashDetectionResult
from fire_detection.detector import FireDetectionResult
from snatch_detection.detector import SnatchResult


@dataclass
class IncidentPayload:
    incident_type: str
    severity: str
    confidence: float
    timestamp: str
    location: Dict[str, Any]
    detection_data: Dict[str, Any]
    evidence_clip_path: Optional[str] = None
    thumbnail_path: Optional[str] = None


def _make_json_serializable(obj: Any) -> Any:
    """Recursively convert numpy arrays and other non-serializable types to JSON-serializable types."""
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, dict):
        return {k: _make_json_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_json_serializable(v) for v in obj]
    if hasattr(obj, '__dict__'):
        return _make_json_serializable(obj.__dict__)
    return obj


class APIClient:
    def __init__(self, base_url: str = "http://localhost:8000/api/v1"):
        self.base_url = base_url
        self.session: Optional[aiohttp.ClientSession] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._queue: asyncio.Queue = asyncio.Queue()
        self._running = False

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop)
        if self._thread:
            self._thread.join(timeout=5)

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._process_queue())

    async def _shutdown(self):
        if self.session:
            await self.session.close()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=10)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session

    def submit_incident(self, payload: IncidentPayload):
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._queue.put(payload), self._loop)

    async def _process_queue(self):
        while self._running:
            try:
                payload = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                await self._send_incident(payload)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                print(f"[APIClient] Queue processing error: {e}")

    async def _send_incident(self, payload: IncidentPayload):
        session = await self._get_session()
        try:
            data = asdict(payload)
            data = _make_json_serializable(data)
            async with session.post(f"{self.base_url}/incidents", json=data) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    print(f"[APIClient] Failed to send incident: {resp.status} - {text}")
                else:
                    print(f"[APIClient] Incident sent: {payload.incident_type}")
        except Exception as e:
            print(f"[APIClient] Error sending incident: {e}")

    async def health_check(self) -> bool:
        try:
            session = await self._get_session()
            async with session.get(f"{self.base_url.replace('/api/v1', '')}/system/health") as resp:
                return resp.status == 200
        except Exception:
            return False


api_client = APIClient()


def map_detection_to_incident(
    detection_type: str,
    confidence: float,
    frame: np.ndarray,
    timestamp: datetime,
    camera_id: str = "CAM-001",
    location_name: str = "MI Road, Jaipur",
    latitude: float = None,
    longitude: float = None,
    detection_data: Dict[str, Any] = None,
    evidence_clip_path: str = None,
    thumbnail_path: str = None,
) -> IncidentPayload:
    severity = "low"
    if confidence >= 0.9:
        severity = "critical"
    elif confidence >= 0.75:
        severity = "high"
    elif confidence >= 0.6:
        severity = "medium"

    type_mapping = {
        "violence": "violence",
        "fight": "violence",
        "fire": "fire",
        "smoke": "fire",
        "crash": "crash",
        "accident": "crash",
        "fall": "fall",
        "snatch": "snatch",
        "snatching": "snatch",
    }

    incident_type = type_mapping.get(detection_type.lower(), "other")

    return IncidentPayload(
        incident_type=incident_type,
        severity=severity,
        confidence=confidence,
        timestamp=timestamp.isoformat(),
        location={
            "latitude": latitude,
            "longitude": longitude,
            "address": location_name if latitude is not None and longitude is not None else f"{location_name} (location unknown)",
            "camera_id": camera_id,
        },
        detection_data=detection_data or {},
        evidence_clip_path=evidence_clip_path,
        thumbnail_path=thumbnail_path,
    )


def create_incident_from_detection(
    frame: np.ndarray,
    detection_result: Any,
    detection_type: str,
    camera_id: str = "CAM-001",
    location_name: str = "MI Road, Jaipur",
    latitude: float = None,
    longitude: float = None,
    timestamp: datetime = None,
) -> Optional[IncidentPayload]:
    if timestamp is None:
        timestamp = datetime.utcnow()

    if hasattr(detection_result, 'confidence'):
        confidence = detection_result.confidence
    elif isinstance(detection_result, dict) and 'confidence' in detection_result:
        confidence = detection_result['confidence']
    else:
        confidence = 0.5

    if confidence < 0.3:
        return None

    evidence_info = evidence_service.save_evidence_clip(
        camera_id=camera_id,
        incident_timestamp=timestamp,
        incident_id=f"{detection_type}_{int(timestamp.timestamp())}",
        pre_seconds=30.0,
        post_seconds=5.0,
    )

    detection_data = {}
    if hasattr(detection_result, 'boxes'):
        detection_data['boxes'] = detection_result.boxes
    elif hasattr(detection_result, 'verdict'):
        detection_data['verdict'] = detection_result.verdict
        detection_data['vote'] = detection_result.vote
        detection_data['p_motion'] = detection_result.p_motion
        detection_data['p_pose'] = detection_result.p_pose
        detection_data['p_context'] = detection_result.p_context
    elif isinstance(detection_result, dict):
        detection_data = detection_result

    return map_detection_to_incident(
        detection_type=detection_type,
        confidence=confidence,
        frame=frame,
        timestamp=timestamp,
        camera_id=camera_id,
        location_name=location_name,
        latitude=latitude,
        longitude=longitude,
        detection_data=detection_data,
        evidence_clip_path=evidence_info['video_path'] if evidence_info else None,
        thumbnail_path=evidence_info['thumbnail_path'] if evidence_info else None,
    )