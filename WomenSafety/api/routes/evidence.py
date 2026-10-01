from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pathlib import Path
import mimetypes
import os

from api.services.evidence_service import evidence_service
from api.services.evidence_storage import EVIDENCE_ROOT
from api.core.config import settings


router = APIRouter(prefix="/evidence", tags=["evidence"])

EVIDENCE_ROOT_V2 = settings.EVIDENCE_ROOT_V2


def _resolve_within_root(root: Path, *segments: str) -> Path:
    """Path-traversal defense shared by every evidence-serving route:
    resolve the fully joined path (collapsing any ".." segments) and
    reject anything that doesn't land strictly inside `root`'s own
    resolved path, checked on the resolved path itself -- not the raw
    string -- so no encoding of ".." can escape the evidence root."""
    candidate = root.joinpath(*segments).resolve()
    resolved_root = root.resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError:
        raise HTTPException(status_code=403, detail="Invalid evidence path")
    return candidate


def _serve_with_range(path: Path, request: Request, media_type: str):
    file_size = os.path.getsize(path)
    range_header = request.headers.get("range")
    if range_header:
        try:
            range_val = range_header.strip().replace("bytes=", "")
            start_str, end_str = range_val.split("-")
            start = int(start_str)
            end = int(end_str) if end_str else file_size - 1
            end = min(end, file_size - 1)
            chunk_size = end - start + 1

            def iter_file():
                with open(path, "rb") as f:
                    f.seek(start)
                    remaining = chunk_size
                    while remaining > 0:
                        data = f.read(min(65536, remaining))
                        if not data:
                            break
                        remaining -= len(data)
                        yield data

            return StreamingResponse(
                iter_file(),
                status_code=206,
                media_type=media_type,
                headers={
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(chunk_size),
                    "Cache-Control": "no-cache",
                },
            )
        except (ValueError, OSError):
            pass

    return StreamingResponse(
        open(path, "rb"),
        media_type=media_type,
        headers={
            "Content-Length": str(file_size),
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-cache",
        },
    )


@router.get("/v2/{camera_id}/{date_str}/{incident_id}/{filename}")
async def get_incident_evidence_v2(camera_id: str, date_str: str, incident_id: str, filename: str, request: Request):
    """Serves a CCTV incident's evidence file (best_frame.jpg,
    annotated_frame.jpg, thumbnail.jpg, clip.mp4) from
    evidence/{camera_id}/{YYYY-MM-DD}/{incident_id}/{filename}, with HTTP
    Range support so clip.mp4 seeks correctly in a browser <video> tag."""
    candidate = _resolve_within_root(EVIDENCE_ROOT_V2, camera_id, date_str, incident_id, filename)
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Evidence file not found")

    media_type, _ = mimetypes.guess_type(str(candidate))
    media_type = media_type or "application/octet-stream"
    if candidate.suffix == ".mp4":
        return _serve_with_range(candidate, request, media_type)
    return FileResponse(path=str(candidate), media_type=media_type)


@router.get("/camera/{camera_id}/{date_str}/{filename}")
async def get_camera_evidence(camera_id: str, date_str: str, filename: str):
    """Serves a camera/device-addendum evidence file from
    evidence/{camera_id}/{date_str}/{filename}. Path-traversal defense:
    build the candidate path, resolve it to an absolute real path (which
    collapses any ".." segments), and reject anything that doesn't land
    strictly inside EVIDENCE_ROOT's own resolved path -- a filename like
    "../../../etc/passwd" or an camera_id/date_str containing ".." cannot
    escape the evidence root no matter how it's encoded, because the
    check happens on the fully-resolved path, not the raw string."""
    candidate = (EVIDENCE_ROOT / camera_id / date_str / filename).resolve()
    root = EVIDENCE_ROOT.resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=403, detail="Invalid evidence path")
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Evidence file not found")

    media_type, _ = mimetypes.guess_type(str(candidate))
    return FileResponse(path=str(candidate), media_type=media_type or "application/octet-stream")


@router.get("")
async def list_evidence_clips():
    return evidence_service.list_clips()


@router.get("/thumbnail/{filename}")
async def get_evidence_thumbnail(filename: str):
    thumb_path = evidence_service.clips_dir / filename
    if not thumb_path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(path=str(thumb_path), media_type="image/jpeg")


@router.get("/{filename}")
async def get_evidence_clip(filename: str, request: Request):
    clip_path = evidence_service.get_clip_path(filename)
    if not clip_path:
        raise HTTPException(status_code=404, detail="Evidence clip not found")

    file_size = os.path.getsize(clip_path)
    media_type = "video/mp4"

    # Support range requests so browser video player can seek
    range_header = request.headers.get("range")
    if range_header:
        try:
            range_val = range_header.strip().replace("bytes=", "")
            start_str, end_str = range_val.split("-")
            start = int(start_str)
            end = int(end_str) if end_str else file_size - 1
            end = min(end, file_size - 1)
            chunk_size = end - start + 1

            def iter_file():
                with open(clip_path, "rb") as f:
                    f.seek(start)
                    remaining = chunk_size
                    while remaining > 0:
                        data = f.read(min(65536, remaining))
                        if not data:
                            break
                        remaining -= len(data)
                        yield data

            return StreamingResponse(
                iter_file(),
                status_code=206,
                media_type=media_type,
                headers={
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(chunk_size),
                    "Cache-Control": "no-cache",
                },
            )
        except Exception:
            pass

    # Full file response
    return StreamingResponse(
        open(clip_path, "rb"),
        media_type=media_type,
        headers={
            "Content-Length": str(file_size),
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-cache",
            "Content-Disposition": f'inline; filename="{filename}"',
        },
    )


@router.delete("/{filename}")
async def delete_evidence_clip(filename: str):
    clip_path = evidence_service.get_clip_path(filename)
    if not clip_path:
        raise HTTPException(status_code=404, detail="Evidence clip not found")
    clip_path.unlink()
    thumb_name = filename.replace(".mp4", "_thumb.jpg")
    thumb_path = evidence_service.clips_dir / thumb_name
    if thumb_path.exists():
        thumb_path.unlink()
    return {"message": "Deleted"}
