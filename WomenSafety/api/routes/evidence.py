from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pathlib import Path
import mimetypes
import os

from api.services.evidence_service import evidence_service


router = APIRouter(prefix="/evidence", tags=["evidence"])


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
