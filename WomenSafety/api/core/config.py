import os
from pathlib import Path
from typing import List
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "Incident Command Dashboard"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"

    BACKEND_CORS_ORIGINS: List[str] = ["*"]

    EVIDENCE_CLIPS_DIR: Path = Path(__file__).parent.parent.parent / "evidence_clips"
    EVIDENCE_CLIP_DURATION_SECONDS: int = 10
    EVIDENCE_PRE_BUFFER_SECONDS: int = 5

    DETECTION_CONFIDENCE_THRESHOLD: float = 0.5

    JAIPUR_CENTER_LAT: float = 26.9124
    JAIPUR_CENTER_LNG: float = 75.7873

    class Config:
        case_sensitive = True
        env_file = ".env"
        extra = "allow"


settings = Settings()

settings.EVIDENCE_CLIPS_DIR.mkdir(parents=True, exist_ok=True)