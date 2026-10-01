"""ARCHIVED, NOT PART OF THE PRODUCT -- see CHANGELOG.md "CCTV Incident
Capture Pipeline" phase. The product is now CCTV-only: /api/v1/detect's
--run-detect path here has no camera_id from the registry, so the live
API will now reject its incident-creation calls (CCTV-only ingestion
requires a registered camera_id). Left for potential future reuse
(e.g. an offline test-fixture generator), not deleted.

Fetches real images via SerpApi's Google Images search, downloads them,
and (optionally) runs each through this project's own /api/v1/detect
endpoint -- the same real detection pipeline used everywhere else in this
project, not a mock.

Usage:
    python scripts/fetch_serpapi_images.py "car crash accident" --count 10 --run-detect
    python scripts/fetch_serpapi_images.py "building on fire" --count 5

Requires SERPAPI_KEY in WomenSafety/.env (already set up).
"""
import argparse
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

SERPAPI_KEY = os.environ.get("SERPAPI_KEY")
DOWNLOAD_DIR = Path(__file__).parent.parent / "scraped_data"
DETECT_URL = "http://localhost:8000/api/v1/detect"
REQUEST_TIMEOUT = 15
MAX_RETRIES = 3


def search_images(query: str, count: int) -> list[dict]:
    if not SERPAPI_KEY:
        print("ERROR: SERPAPI_KEY not set in WomenSafety/.env", file=sys.stderr)
        sys.exit(1)

    params = {
        "engine": "google_images",
        "q": query,
        "api_key": SERPAPI_KEY,
        "ijn": "0",
    }
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get("https://serpapi.com/search", params=params, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 429:
                wait = 2 ** attempt
                print(f"SerpApi rate-limited (429), backing off {wait}s (attempt {attempt+1}/{MAX_RETRIES})")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                err = data["error"]
                if "run out of searches" in err.lower() or "quota" in err.lower():
                    print(f"SerpApi quota exhausted: {err}", file=sys.stderr)
                    sys.exit(2)
                print(f"SerpApi error: {err}", file=sys.stderr)
                sys.exit(1)
            return data.get("images_results", [])[:count]
        except requests.exceptions.RequestException as e:
            last_error = e
            wait = 2 ** attempt
            print(f"request failed ({type(e).__name__}), retrying in {wait}s (attempt {attempt+1}/{MAX_RETRIES})")
            time.sleep(wait)
    print(f"ERROR: search_images failed after {MAX_RETRIES} attempts: {last_error}", file=sys.stderr)
    sys.exit(1)


def download_image(url: str, dest: Path) -> bool:
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        return True
    except Exception as e:
        print(f"  failed to download {url}: {e}")
        return False


# /api/v1/detect requires latitude/longitude as mandatory form fields
# (api/routes/detect.py: Form(...)) -- this script has no real location
# source for a generic image search (unlike the news scrapers, there is
# no headline to extract a place from), so it CANNOT honestly call
# /detect without fabricating coordinates. The previous version of this
# script worked around that by cycling through a hardcoded 5-point
# Jaipur coordinate list (DEFAULT_LOCATIONS) -- exactly the kind of
# dummy-coordinate fallback this phase's rules forbid. Deleted entirely
# rather than replaced: --run-detect now requires the caller to supply
# a real --latitude/--longitude for the whole batch (since they know
# where these images are meant to represent, if anywhere), and refuses
# to run otherwise. This is a real capability reduction, not a silent
# workaround -- see CHANGELOG.md.
def run_detect(image_path: Path, camera_id: str, location_name: str, lat: float, lng: float) -> dict:
    with open(image_path, "rb") as f:
        files = {"file": (image_path.name, f, "image/jpeg")}
        data = {
            "camera_id": camera_id,
            "location_name": location_name,
            "latitude": str(lat),
            "longitude": str(lng),
            "min_confidence": "0.3",
        }
        resp = requests.post(DETECT_URL, files=files, data=data, timeout=120)
        return resp.json()


def main():
    parser = argparse.ArgumentParser(description="Fetch real images via SerpApi and optionally run them through the detection pipeline")
    parser.add_argument("query", help="Search query, e.g. 'car crash accident'")
    parser.add_argument("--count", type=int, default=10, help="Number of images to fetch")
    parser.add_argument("--run-detect", action="store_true", help="Also POST each downloaded image to /api/v1/detect")
    parser.add_argument("--camera-prefix", default="CAM-SCRAPE", help="Camera ID prefix for detect calls")
    parser.add_argument("--latitude", type=float, default=None,
                         help="Real latitude for these images' location. Required with --run-detect -- "
                              "there is no default/dummy location anymore.")
    parser.add_argument("--longitude", type=float, default=None,
                         help="Real longitude for these images' location. Required with --run-detect.")
    parser.add_argument("--location-name", default=None,
                         help="Human-readable location text for these images. Required with --run-detect.")
    args = parser.parse_args()

    if args.run_detect and (args.latitude is None or args.longitude is None or not args.location_name):
        print("ERROR: --run-detect requires --latitude, --longitude, and --location-name -- "
              "this script no longer fabricates a default location.", file=sys.stderr)
        sys.exit(1)

    DOWNLOAD_DIR.mkdir(exist_ok=True)
    safe_query = "".join(c if c.isalnum() else "_" for c in args.query)[:40]

    print(f"Searching SerpApi for: {args.query!r} ({args.count} images)")
    results = search_images(args.query, args.count)
    print(f"Got {len(results)} results\n")

    for i, item in enumerate(results):
        img_url = item.get("original") or item.get("thumbnail")
        if not img_url:
            continue
        dest = DOWNLOAD_DIR / f"{safe_query}_{i:02d}.jpg"
        print(f"[{i+1}/{len(results)}] {img_url[:80]}...")
        ok = download_image(img_url, dest)
        if not ok:
            continue
        print(f"  saved to {dest}")

        if args.run_detect:
            camera_id = f"{args.camera_prefix}-{i:02d}"
            result = run_detect(dest, camera_id, args.location_name, args.latitude, args.longitude)
            if result.get("incident_created"):
                inc = result["incident"]
                print(f"  -> INCIDENT CREATED: {inc['incident_type']} conf={inc['confidence']:.2f} sev={inc['severity']}")
            else:
                vio = result.get("model_results", {}).get("violence", {})
                print(f"  -> no incident (best guess: {vio.get('label')!r} conf={vio.get('confidence', 0):.2f})")


if __name__ == "__main__":
    main()
