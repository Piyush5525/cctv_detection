"""Evidence file storage for camera-sourced incidents.

PARTIALLY ARCHIVED (see CHANGELOG.md "CCTV Incident Capture Pipeline /
Scope Reset" phase): the functions evidence_dir_for(),
save_evidence_file(), and make_thumbnail() are still available to the
live product. The EXIF-GPS and ffprobe-GPS extraction functions
(extract_image_gps_and_time, extract_video_gps_and_time) are CANCELLED
features (mobile/upload-GPS scope removed) and must not be called by
any live code path. They are left here, undeleted, only because
removing them would cause import errors in any archived code that
happens to reference this module.
"""
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS

EVIDENCE_ROOT = Path(__file__).parent.parent.parent / "evidence"
THUMBNAIL_WIDTH = 320


def evidence_dir_for(camera_id: str, when: Optional[datetime] = None) -> Path:
    when = when or datetime.now(timezone.utc)
    date_str = when.strftime("%Y-%m-%d")
    # camera_id is used as a path segment -- sanitize it so a malicious or
    # malformed camera_id can never be used to write outside EVIDENCE_ROOT
    # (e.g. "../../etc"). Same principle as the read-side path validation.
    safe_camera_id = "".join(c for c in camera_id if c.isalnum() or c in ("-", "_")) or "unknown-camera"
    d = EVIDENCE_ROOT / safe_camera_id / date_str
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_evidence_file(camera_id: str, filename: str, data: bytes, when: Optional[datetime] = None) -> Path:
    d = evidence_dir_for(camera_id, when)
    dest = d / filename
    dest.write_bytes(data)
    return dest


def make_thumbnail(image_path: Path, width: int = THUMBNAIL_WIDTH) -> Optional[Path]:
    """Creates a {width}px-wide JPEG thumbnail next to image_path, named
    {stem}_thumb.jpg. Returns None if the source can't be opened as an
    image (e.g. it's actually a video -- video thumbnails are handled by
    the existing evidence_service's frame-grab logic, not duplicated here)."""
    try:
        img = Image.open(image_path)
        img = img.convert("RGB")
        ratio = width / img.width
        height = max(1, int(img.height * ratio))
        img = img.resize((width, height))
        thumb_path = image_path.with_name(f"{image_path.stem}_thumb.jpg")
        img.save(thumb_path, "JPEG", quality=85)
        return thumb_path
    except Exception as e:
        print(f"evidence_storage: thumbnail generation failed for {image_path}: {e}")
        return None


def extract_image_gps_and_time(image_path: Path) -> dict:
    """Reads EXIF GPS + DateTimeOriginal from an image via Pillow. Returns
    {"latitude", "longitude", "captured_at"} with any field that couldn't
    be read left as None -- never a guessed/default value."""
    result = {"latitude": None, "longitude": None, "captured_at": None}
    try:
        img = Image.open(image_path)
        exif = img.getexif()
        if not exif:
            return result

        # Standard EXIF tags live in the top-level IFD; GPS lives in a
        # nested IFD Pillow exposes via get_ifd(0x8825).
        tag_map = {TAGS.get(k, k): v for k, v in exif.items()}
        date_str = tag_map.get("DateTimeOriginal") or tag_map.get("DateTime")
        if date_str:
            try:
                # EXIF datetime format: "YYYY:MM:DD HH:MM:SS", assumed local
                # to the device with no timezone info -- treated as UTC
                # here since we have no better information, same honesty
                # principle as everywhere else (no invented timezone).
                dt = datetime.strptime(date_str, "%Y:%m:%d %H:%M:%S").replace(tzinfo=timezone.utc)
                result["captured_at"] = dt.isoformat()
            except ValueError:
                pass

        gps_ifd = exif.get_ifd(0x8825) if hasattr(exif, "get_ifd") else None
        if gps_ifd:
            gps_tag_map = {GPSTAGS.get(k, k): v for k, v in gps_ifd.items()}
            lat = _convert_gps_coord(gps_tag_map.get("GPSLatitude"), gps_tag_map.get("GPSLatitudeRef"))
            lng = _convert_gps_coord(gps_tag_map.get("GPSLongitude"), gps_tag_map.get("GPSLongitudeRef"))
            result["latitude"] = lat
            result["longitude"] = lng
    except Exception as e:
        print(f"evidence_storage: EXIF extraction failed for {image_path}: {e}")
    return result


def _convert_gps_coord(value, ref) -> Optional[float]:
    if value is None or ref is None:
        return None
    try:
        degrees, minutes, seconds = value
        decimal = float(degrees) + float(minutes) / 60 + float(seconds) / 3600
        if ref in ("S", "W"):
            decimal = -decimal
        return decimal
    except Exception:
        return None


def extract_video_gps_and_time(video_path: Path) -> dict:
    """Reads container-level GPS/creation-time metadata from a video via
    ffprobe (JSON output), if ffprobe is installed and the metadata is
    present. Returns the same shape as extract_image_gps_and_time --
    every field left None if genuinely absent, never guessed."""
    result = {"latitude": None, "longitude": None, "captured_at": None}
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(video_path)],
            capture_output=True, text=True, timeout=15,
        )
        if proc.returncode != 0:
            return result
        data = json.loads(proc.stdout)
        tags = data.get("format", {}).get("tags", {})

        creation_time = tags.get("creation_time")
        if creation_time:
            try:
                dt = datetime.fromisoformat(creation_time.replace("Z", "+00:00"))
                result["captured_at"] = dt.isoformat()
            except ValueError:
                pass

        location_tag = tags.get("location") or tags.get("com.apple.quicktime.location.ISO6709")
        if location_tag:
            lat, lng = _parse_iso6709(location_tag)
            result["latitude"] = lat
            result["longitude"] = lng
    except FileNotFoundError:
        print("evidence_storage: ffprobe not found on PATH -- video metadata extraction skipped")
    except Exception as e:
        print(f"evidence_storage: ffprobe metadata extraction failed for {video_path}: {e}")
    return result


def _parse_iso6709(value: str) -> tuple[Optional[float], Optional[float]]:
    """Parses an ISO 6709 location string like '+19.0550+072.8692/' (the
    format QuickTime/Android commonly embed) into (lat, lng)."""
    import re
    m = re.match(r"^([+-]\d+\.?\d*)([+-]\d+\.?\d*)", value)
    if not m:
        return None, None
    try:
        return float(m.group(1)), float(m.group(2))
    except ValueError:
        return None, None
