"""ARCHIVED, NOT PART OF THE PRODUCT (see CHANGELOG.md "CCTV Incident
Capture Pipeline" phase): the product now handles ONLY fixed-CCTV
incidents, whose location always comes from the camera registry. This
script fetches news, which has no capturing device and no verifiable
location -- keeping it working is out of scope. Its previous live
output was moved to archive/news_scrape_incidents.json and excluded
from the live incident store/API. Left in the repo, unmodified and
not deleted, only in case a future phase decides to reintroduce a
clearly-labeled news feed; --create-incidents will now be rejected by
the live API's CCTV-only ingestion path if run again.

Fetches REAL incident news from anywhere in India via SerpApi's Google
News engine. Writes every kept record to scraped_incidents.json (the
source of truth, keyed by sha1 of the normalized source URL) and POSTs
only genuinely-new records to this project's own API. Re-running this
script is idempotent: it adds 0 duplicate records and never overwrites
a record whose `verified` field is already true.

No incident here has ever been scored by a CV model -- confidence is
always null for scraped records. The category is a controlled value
(road_accident | fire | assault | snatching | other), assigned by an
explicit keyword classifier with no guessing: uncertain/conflicting
headlines become "other".

Usage:
    python scripts/fetch_india_incidents.py "India road accident CCTV" --count 20 --create-incidents
    python scripts/fetch_india_incidents.py "Mumbai fire news" --count 20 --create-incidents

Requires SERPAPI_KEY in WomenSafety/.env (already set up).
"""
import argparse
import io
import json
import os
import re
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import requests
from dotenv import load_dotenv

if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))
from scrape_pipeline import (  # noqa: E402
    ScrapedIncident, check_relevance, classify_category, is_stale, geocode,
    make_id, load_store, save_store, log_dropped, MAX_AGE_DAYS,
)

load_dotenv(Path(__file__).parent.parent / ".env")

SERPAPI_KEY = os.environ.get("SERPAPI_KEY")
API_BASE = "http://localhost:8000/api/v1"
DOWNLOAD_DIR = Path(__file__).parent.parent / "evidence_clips"
REQUEST_TIMEOUT = 15
MAX_RETRIES = 3

# Places to try extracting from a headline -- unchanged from the previous
# version of this script (this list is not in the "confidence/schema"
# scope of this phase, only its downstream handling is).
INDIAN_CITIES = sorted([
    "Navi Mumbai", "Mumbai", "New Delhi", "Delhi", "Bengaluru", "Bangalore",
    "Hyderabad", "Ahmedabad", "Chennai", "Kolkata", "Surat", "Pune", "Jaipur",
    "Lucknow", "Kanpur", "Nagpur", "Indore", "Thane", "Bhopal", "Visakhapatnam",
    "Pimpri-Chinchwad", "Patna", "Vadodara", "Ghaziabad", "Ludhiana", "Agra",
    "Nashik", "Faridabad", "Meerut", "Rajkot", "Kalyan-Dombivli", "Vasai-Virar",
    "Varanasi", "Srinagar", "Aurangabad", "Dhanbad", "Amritsar",
    "Allahabad", "Prayagraj", "Ranchi", "Howrah", "Coimbatore", "Jabalpur",
    "Gwalior", "Vijayawada", "Jodhpur", "Madurai", "Raipur", "Kota", "Guwahati",
    "Chandigarh", "Solapur", "Hubli-Dharwad", "Bareilly", "Moradabad", "Mysore",
    "Mysuru", "Gurugram", "Gurgaon", "Aligarh", "Jalandhar", "Bhubaneswar",
    "Salem", "Warangal", "Guntur", "Bhiwandi", "Saharanpur", "Gorakhpur",
    "Bikaner", "Amravati", "Noida", "Jamshedpur", "Bhilai", "Cuttack",
    "Firozabad", "Kochi", "Cochin", "Nellore", "Bhavnagar", "Dehradun",
    "Durgapur", "Asansol", "Rourkela", "Nanded", "Kolhapur", "Ajmer",
    "Akola", "Gulbarga", "Jamnagar", "Ujjain", "Loni", "Siliguri", "Jhansi",
    "Ulhasnagar", "Jammu", "Sangli-Miraj", "Mangalore", "Mangaluru", "Erode",
    "Belgaum", "Belagavi", "Ambattur", "Tirunelveli", "Malegaon", "Gaya",
    "Jalgaon", "Udaipur", "Maheshtala", "Tirupur", "Davanagere", "Kozhikode",
    "Kurnool", "Rajpur Sonarpur", "Bokaro", "South Dumdum", "Bellary",
    "Ballari", "Patiala", "Gopalpur", "Agartala", "Bhagalpur", "Muzaffarnagar",
    "Bhatpara", "Panihati", "Latur", "Dhule", "Rohtak", "Korba", "Bhilwara",
    "Berhampur", "Muzaffarpur", "Ahmednagar", "Mathura", "Kollam", "Avadi",
    "Kadapa", "Kamarhati", "Sambalpur", "Bilaspur", "Shahjahanpur", "Satara",
    "Bijapur", "Vijayapura", "Rampur", "Shimoga", "Shivamogga", "Chandrapur",
    "Junagadh", "Thrissur", "Alwar", "Bardhaman", "Kulti", "Kakinada",
    "Nizamabad", "Parbhani", "Tumkur", "Tumakuru", "Khammam", "Ozhukarai",
    "Bihar Sharif", "Panipat", "Darbhanga", "Bally", "Aizawl", "Dewas",
    "Ichalkaranji", "Karnal", "Bathinda", "Jalna", "Eluru", "Kirari Suleman Nagar",
    "Barasat", "Purnia", "Satna", "Mau", "Sonipat", "Farrukhabad", "Sagar",
    "Durg", "Imphal", "Ratlam", "Hapur", "Arrah", "Anantapur", "Karimnagar",
    "Etawah", "Ambernath", "North Dumdum", "Bharatpur", "Begusarai",
    "Gandhinagar", "Baranagar", "Tiruvottiyur", "Puducherry",
    "Sikar", "Thoothukudi", "Rewa", "Mirzapur", "Raichur", "Pali",
    "Ramagundam", "Haridwar", "Vijayanagaram", "Katihar", "Nagercoil",
    "Sri Ganganagar", "Ganganagar", "Karawal Nagar", "Mango", "Thanjavur",
    "Bulandshahr", "Uluberia", "Katni", "Sambhal", "Singrauli", "Nadiad",
    "Secunderabad", "Naihati", "Yamunanagar", "Bidhannagar", "Pallavaram",
    "Bidar", "Munger", "Panchkula", "Burhanpur", "Raurkela", "Kharagpur",
    "Dindigul", "Gandhidham", "Hospet", "Nangloi Jat", "Malda", "Ongole",
    "Deoghar", "Chapra", "Haldia", "Khandwa", "Nandyal", "Morena",
    "Amroha", "Anand", "Bhind", "Bhalswa Jahangir Pur", "Madhyamgram",
    "Bhiwani", "Berhampore", "Ambala", "Morvi", "Fatehpur", "Rae Bareli",
], key=len, reverse=True)

NON_INDIA_PLACE_QUALIFIERS = re.compile(
    r"\btownship\b|\bcounty\b|\bprovince\b|\bdistrict attorney\b|\bsheriff\b|\b(WLNS|WILX)\b",
    re.IGNORECASE,
)


def find_place_mentions(text: str) -> list[str]:
    if NON_INDIA_PLACE_QUALIFIERS.search(text):
        return []
    found = []
    lower = text.lower()
    for city in INDIAN_CITIES:
        if re.search(rf"\b{re.escape(city.lower())}\b", lower):
            found.append(city)
    return found


def search_news_with_retry(query: str, count: int) -> list[dict]:
    """SerpApi call with timeout, retry+exponential-backoff, and explicit
    handling of SerpApi error payloads / quota exhaustion. Never logs the
    API key."""
    if not SERPAPI_KEY:
        print("ERROR: SERPAPI_KEY not set in WomenSafety/.env", file=sys.stderr)
        sys.exit(1)

    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(
                "https://serpapi.com/search",
                params={"engine": "google_news", "q": query, "api_key": SERPAPI_KEY},
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code == 429:
                wait = 2 ** attempt
                print(f"    SerpApi rate-limited (429), backing off {wait}s (attempt {attempt+1}/{MAX_RETRIES})")
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
                return []
            return data.get("news_results", [])[:count]
        except requests.exceptions.RequestException as e:
            last_error = e
            wait = 2 ** attempt
            print(f"    request failed ({type(e).__name__}), retrying in {wait}s (attempt {attempt+1}/{MAX_RETRIES})")
            time.sleep(wait)
    print(f"ERROR: search_news failed after {MAX_RETRIES} attempts: {last_error}", file=sys.stderr)
    return []


def download_thumbnail(url: str, dest: Path) -> bool:
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        return True
    except Exception:
        return False


ILLUSTRATION_MIN_UNIQUE_COLORS = 3000


def looks_like_real_photo(path: Path) -> bool:
    try:
        img = cv2.imread(str(path))
        if img is None:
            return False
        small = cv2.resize(img, (100, 100))
        unique_colors = len(np.unique(small.reshape(-1, 3), axis=0))
        return unique_colors >= ILLUSTRATION_MIN_UNIQUE_COLORS
    except Exception:
        return False


def create_incident_from_record(rec: ScrapedIncident) -> dict:
    """POSTs a validated ScrapedIncident to the live incident API.
    confidence is always None (null) here -- no CV model has run."""
    # Map controlled category -> the incident_type taxonomy the existing
    # dashboard/API already uses, so this doesn't require a backend schema
    # migration (out of scope for this phase).
    type_map = {
        "road_accident": "crash", "fire": "fire", "assault": "violence",
        "snatching": "snatch", "women_safety": "women_safety", "fall": "fall",
        "other": "other",
    }
    severity = (
        "critical" if rec.category in ("assault", "women_safety") else
        "high" if rec.category in ("fire", "road_accident") else
        "medium"
    )
    # The live backend's Location model requires non-null latitude/longitude
    # (api/models/incident.py) -- out of this phase's named scope to widen.
    # Rather than substitute a default/fake coordinate (explicitly forbidden
    # -- (0.0, 0.0) is a real ocean point, not a safe placeholder), a record
    # with no real coordinates is not sent to the live incident API at all.
    # It still exists in scraped_incidents.json with latitude=None,
    # longitude=None, location_precision="unknown" -- the source-of-truth
    # record is honest even though the live dashboard can't display it yet.
    # See CHANGELOG.md for why this wasn't resolved further in Phase 1.
    if rec.latitude is None or rec.longitude is None:
        raise ValueError("no real coordinates -- not sending to live API (Location model requires non-null lat/lng)")
    payload = {
        "incident_type": type_map[rec.category],
        "severity": severity,
        "confidence": None,
        "timestamp": rec.published_at,
        "location": {
            "latitude": rec.latitude,
            "longitude": rec.longitude,
            "address": rec.location_text,
            "camera_id": "NEWS-SCRAPE",
        },
        "detection_data": {
            "source": "news_scrape",
            "notes": f"{rec.title} (source: {rec.source_name}, {rec.source_url})",
            "scraped_id": rec.id,
            "location_precision": rec.location_precision,
            "verified": rec.verified,
        },
        "thumbnail_path": rec.image_url,
    }
    resp = requests.post(f"{API_BASE}/incidents", json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


def main():
    parser = argparse.ArgumentParser(description="Fetch real India-wide incident news via SerpApi and create real incidents from them")
    parser.add_argument("query", help="Search query, e.g. 'Mumbai road accident'")
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--create-incidents", action="store_true")
    parser.add_argument("--max-age-days", type=int, default=MAX_AGE_DAYS)
    args = parser.parse_args()

    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    store = load_store()

    print(f"Searching Google News (via SerpApi) for: {args.query!r} ({args.count} articles)")
    articles = search_news_with_retry(args.query, args.count)
    print(f"Got {len(articles)} articles\n")

    stats = {"created": 0, "already_posted": 0, "dropped_stale": 0, "dropped_irrelevant": 0,
              "dropped_no_photo": 0, "dropped_no_location": 0, "dropped_invalid_schema": 0,
              "dropped_duplicate": 0}

    for i, art in enumerate(articles):
        title = art.get("title", "")
        source = art.get("source", {}).get("name", "unknown")
        link = art.get("link", "")
        iso_date = art.get("iso_date")
        thumb_url = art.get("thumbnail")

        print(f"[{i+1}/{len(articles)}] {title}")
        print(f"    source={source} date={iso_date}")

        if not link:
            print("    SKIPPED: no source URL\n")
            stats["dropped_invalid_schema"] += 1
            continue

        record_id = make_id(link)
        if record_id in store:
            print("    SKIPPED: already in scraped_incidents.json (idempotent re-run)\n")
            stats["dropped_duplicate"] += 1
            continue

        reason = check_relevance(title)
        if reason:
            print(f"    SKIPPED: not a real incident ({reason})\n")
            log_dropped(record_id, title, reason)
            stats["dropped_irrelevant"] += 1
            continue

        category = classify_category(title)
        if category == "other":
            print("    SKIPPED: no category keywords matched (uncertain, not guessed)\n")
            log_dropped(record_id, title, "not_incident")
            stats["dropped_irrelevant"] += 1
            continue

        if not iso_date:
            print("    SKIPPED: no publish date\n")
            log_dropped(record_id, title, "invalid_schema", detail="missing published_at")
            stats["dropped_invalid_schema"] += 1
            continue

        stale, age_days = is_stale(iso_date, args.max_age_days)
        if stale:
            print(f"    SKIPPED: stale ({age_days} days old, limit {args.max_age_days})\n")
            log_dropped(record_id, title, "stale", age_days=age_days)
            stats["dropped_stale"] += 1
            continue

        # Location: try the most specific place mention first (still
        # city-level extraction from the headline text, per spec -- a
        # finer locality/landmark/road tier would need snippet/body text
        # this SerpApi engine doesn't return, so precision is honestly
        # capped at "city"/"area" here, never faked as "exact").
        places = find_place_mentions(title)
        located = None
        for place in places:
            coords = geocode(f"{place}, India")
            if coords:
                located = (coords, place)
                print(f"    matched place: {place!r} -> ({coords['latitude']:.4f}, {coords['longitude']:.4f}) [{coords['precision']}]")
                break

        if located:
            coords, place = located
            latitude, longitude = coords["latitude"], coords["longitude"]
            location_text = coords["display_name"]
            location_precision = coords["precision"]
        else:
            print("    no specific, geocodable Indian place found -- keeping with null coordinates")
            latitude, longitude, location_text, location_precision = None, None, "unknown", "unknown"

        thumb_path = None
        if thumb_url:
            import hashlib
            unique_id = hashlib.md5((link or thumb_url).encode()).hexdigest()[:12]
            thumb_path = DOWNLOAD_DIR / f"article_{unique_id}.jpg"
            if download_thumbnail(thumb_url, thumb_path):
                if looks_like_real_photo(thumb_path):
                    print(f"    thumbnail saved: {thumb_path}")
                else:
                    print("    thumbnail rejected (looks like a stock illustration/logo, not a real photo)")
                    thumb_path.unlink(missing_ok=True)
                    thumb_path = None
            else:
                thumb_path = None

        if thumb_path is None:
            print("    SKIPPED: no real photo available\n")
            log_dropped(record_id, title, "no_real_photo", detail="no real photo available")
            stats["dropped_no_photo"] += 1
            continue

        from datetime import datetime, timezone
        try:
            rec = ScrapedIncident(
                id=record_id,
                title=title,
                category=category,
                description="",
                source_name=source,
                source_url=link,
                published_at=iso_date,
                location_text=location_text,
                latitude=latitude,
                longitude=longitude,
                location_precision=location_precision,
                image_url=str(thumb_path) if thumb_path else None,
                fetched_at=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as e:
            print(f"    SKIPPED: schema validation failed: {e}\n")
            log_dropped(record_id, title, "invalid_schema", detail=str(e))
            stats["dropped_invalid_schema"] += 1
            continue

        store[record_id] = json.loads(rec.model_dump_json())
        save_store(store)

        print(f"    classified as: category={category} precision={location_precision}")

        if args.create_incidents:
            try:
                inc = create_incident_from_record(rec)
                print(f"    -> INCIDENT CREATED: {inc['incident_id']}")
                stats["created"] += 1
            except Exception as e:
                print(f"    -> FAILED to create incident: {e}")

        print()

    print(f"Created {stats['created']}/{len(articles)} incidents.")
    print(f"Dropped: {stats['dropped_stale']} stale, {stats['dropped_irrelevant']} irrelevant, "
          f"{stats['dropped_no_photo']} no-real-photo, {stats['dropped_no_location']} no-location, "
          f"{stats['dropped_invalid_schema']} invalid-schema, {stats['dropped_duplicate']} already-posted.")


if __name__ == "__main__":
    main()
