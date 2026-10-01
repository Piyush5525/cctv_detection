"""ARCHIVED, NOT PART OF THE PRODUCT -- see CHANGELOG.md "CCTV Incident
Capture Pipeline" phase. The product is now CCTV-only: --run-detect
here has no camera_id from the registry, so the live API will now
reject its incident-creation calls (CCTV-only ingestion requires a
registered camera_id). Left for potential future reuse (e.g. an
offline test-fixture generator), not deleted.

Fetches REAL dashcam/CCTV incident videos: searches YouTube (via SerpApi's
Google Videos engine, filtered to youtube.com links since those download
reliably) for real incident footage, downloads the actual video file with
yt-dlp, then runs it through this project's own /api/v1/detect endpoint --
the same real detection pipeline (sampled frames, temporal-consistency and
whole-frame-box filtering) used everywhere else in this project.

Usage:
    python scripts/fetch_incident_videos.py "dashcam car crash caught on camera" --count 5 --run-detect
    python scripts/fetch_incident_videos.py "CCTV footage fire building" --count 5 --run-detect
    python scripts/fetch_incident_videos.py "CCTV footage street fight" --count 5 --run-detect

Requires SERPAPI_KEY in WomenSafety/.env (already set up) and yt-dlp
(pip install yt-dlp).

Videos are capped at --max-duration seconds (default 120) so a fetch can't
accidentally pull down a 2-hour compilation and burn through disk/CPU
running detection on it.
"""
import argparse
import os
import sys
from pathlib import Path

import requests
import yt_dlp
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

SERPAPI_KEY = os.environ.get("SERPAPI_KEY")
DETECT_URL = "http://localhost:8000/api/v1/detect"
DOWNLOAD_DIR = Path(__file__).parent.parent / "scraped_data" / "videos"


def search_videos(query: str, count: int) -> list[dict]:
    if not SERPAPI_KEY:
        print("ERROR: SERPAPI_KEY not set in WomenSafety/.env", file=sys.stderr)
        sys.exit(1)
    resp = requests.get(
        "https://serpapi.com/search",
        params={"engine": "google_videos", "q": query, "api_key": SERPAPI_KEY},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        print(f"SerpApi error: {data['error']}", file=sys.stderr)
        sys.exit(1)
    results = data.get("video_results", [])
    youtube_only = [r for r in results if "youtube.com" in r.get("link", "")]
    return youtube_only[:count]


def download_video(url: str, dest_template: str, max_duration: int) -> Path | None:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "mp4[height<=480]/best[height<=480]/best",
        "outtmpl": dest_template,
        "match_filter": yt_dlp.utils.match_filter_func(f"duration <= {max_duration}"),
        "noplaylist": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info is None:
                return None
            path = ydl.prepare_filename(info)
            return Path(path) if Path(path).exists() else None
    except Exception as e:
        print(f"  yt-dlp failed: {e}")
        return None


def run_detect(video_path: Path, camera_id: str, location_name: str, lat: float, lng: float, min_confidence: float) -> dict:
    with open(video_path, "rb") as f:
        files = {"file": (video_path.name, f, "video/mp4")}
        data = {
            "camera_id": camera_id,
            "location_name": location_name,
            "latitude": str(lat),
            "longitude": str(lng),
            "min_confidence": str(min_confidence),
        }
        resp = requests.post(DETECT_URL, files=files, data=data, timeout=300)
        return resp.json()


def main():
    parser = argparse.ArgumentParser(description="Fetch real dashcam/CCTV incident videos via SerpApi+yt-dlp and run them through the real detection pipeline")
    parser.add_argument("query", help="Search query, e.g. 'dashcam car crash caught on camera'")
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--max-duration", type=int, default=120, help="Skip videos longer than this many seconds")
    parser.add_argument("--run-detect", action="store_true", help="Also POST each downloaded video to /api/v1/detect")
    parser.add_argument("--camera-prefix", default="CAM-VID", help="Camera ID prefix for detect calls")
    parser.add_argument("--min-confidence", type=float, default=0.5)
    parser.add_argument("--latitude", type=float, default=None,
                         help="Real latitude for these videos' location. Required with --run-detect -- "
                              "there is no default/dummy location anymore.")
    parser.add_argument("--longitude", type=float, default=None,
                         help="Real longitude for these videos' location. Required with --run-detect.")
    parser.add_argument("--location-name", default=None,
                         help="Human-readable location text for these videos. Required with --run-detect.")
    args = parser.parse_args()

    if args.run_detect and (args.latitude is None or args.longitude is None or not args.location_name):
        print("ERROR: --run-detect requires --latitude, --longitude, and --location-name -- "
              "this script no longer fabricates a default location.", file=sys.stderr)
        sys.exit(1)

    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_query = "".join(c if c.isalnum() else "_" for c in args.query)[:40]

    print(f"Searching YouTube (via SerpApi Google Videos) for: {args.query!r} ({args.count} videos, max {args.max_duration}s each)")
    results = search_videos(args.query, args.count)
    print(f"Got {len(results)} YouTube results\n")

    for i, item in enumerate(results):
        title = item.get("title", "")
        link = item.get("link", "")
        duration = item.get("duration", "?")
        print(f"[{i+1}/{len(results)}] {title} ({duration}) -- {link}")

        dest_template = str(DOWNLOAD_DIR / f"{safe_query}_{i:02d}.%(ext)s")
        video_path = download_video(link, dest_template, args.max_duration)
        if video_path is None:
            print("  skipped (too long, download failed, or unavailable)\n")
            continue
        print(f"  saved to {video_path}")

        if args.run_detect:
            camera_id = f"{args.camera_prefix}-{i:02d}"
            result = run_detect(video_path, camera_id, args.location_name, args.latitude, args.longitude, args.min_confidence)
            incidents = result.get("incidents_created", [])
            findings = result.get("findings", [])
            if incidents:
                for inc in incidents:
                    print(f"  -> INCIDENT CREATED: {inc['incident_type']} conf={inc['confidence']:.2f} sev={inc['severity']}")
            else:
                print(f"  -> no incident (findings: {findings or 'none'})")
        print()


if __name__ == "__main__":
    main()
