"""Nearby emergency services lookup via SerpApi's google_maps engine
(CHANGELOG.md "Dispatch Backend" phase). DATA ONLY: this module looks
up and caches real hospital/police/fire station info (name, address,
phone, rating, coordinates) for display/routing purposes -- it never
calls or messages any of these numbers itself (see
api/services/safety_guard.py and notification_service.py for the
actual outbound-contact safety rules; those numbers are NEVER dialed
regardless of what this module returns).

Reuses the same SERPAPI_KEY already configured for the archived
news-scrape scripts (scripts/fetch_india_incidents.py) -- read directly
from os.environ, never logged, never written to the cache file or any
response.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from math import radians, sin, cos, sqrt, atan2
from pathlib import Path
from typing import Optional

import requests

from api.core.config import settings

SERPAPI_SEARCH_URL = "https://serpapi.com/search"

CATEGORY_QUERIES = {
    "hospital": "hospital",
    "police": "police station",
    "fire": "fire station",
}

# A found result's own `type`/`types` should plausibly match the category
# we searched for -- SerpApi's local-business search occasionally returns
# an unrelated nearby business for an ambiguous query. Flagged (not
# dropped) rather than silently trusted, since a wrong-looking match is
# still potentially useful information, just needs a visible caveat.
EXPECTED_TYPE_KEYWORDS = {
    "hospital": ("hospital", "clinic", "medical", "emergency care"),
    "police": ("police",),
    "fire": ("fire",),
}

_api_call_count = 0  # process-lifetime counter, reset per run per MAX_API_CALLS_PER_RUN's own docstring


class NearbyServicesError(Exception):
    """Structured error for a failed SerpApi lookup -- carries enough
    detail for the API layer to report a real reason (timeout, HTTP
    error, quota) rather than a bare 500, but never a secret."""
    def __init__(self, message: str, category: Optional[str] = None):
        super().__init__(message)
        self.category = category


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return r * 2 * atan2(sqrt(a), sqrt(1 - a))


def _load_cache() -> dict:
    path = settings.NEARBY_SERVICES_CACHE_PATH
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    path = settings.NEARBY_SERVICES_CACHE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def _cache_entry_fresh(entry: dict) -> bool:
    try:
        cached_at = datetime.fromisoformat(entry["cached_at"])
    except Exception:
        return False
    age_days = (datetime.now(timezone.utc) - cached_at).total_seconds() / 86400
    return age_days < settings.NEARBY_SERVICES_CACHE_TTL_DAYS


def _city_from_place_text(place_text: str) -> str:
    """Cameras' place_text is "<locality>, <City>" (see config/cameras.json,
    e.g. "MI Road, Jaipur") -- the city is the last comma-separated
    segment. Falls back to the whole string if there's no comma, rather
    than guessing or fabricating a city name."""
    parts = [p.strip() for p in place_text.split(",") if p.strip()]
    # No comma => no "<locality>, <City>" structure (e.g. a free-text label like
    # "Demo phone installation"): don't put that text in the query as a fake city;
    # the lat/lng ("ll") already localises the search.
    return parts[-1] if len(parts) > 1 else ""


def _looks_like_right_type(category: str, result: dict) -> bool:
    keywords = EXPECTED_TYPE_KEYWORDS.get(category, ())
    haystack = (result.get("type", "") + " " + " ".join(result.get("types", []))).lower()
    return any(k in haystack for k in keywords)


def _query_serpapi(query: str, lat: float, lng: float) -> list[dict]:
    global _api_call_count
    if _api_call_count >= settings.NEARBY_SERVICES_MAX_API_CALLS_PER_RUN:
        raise NearbyServicesError(
            f"hard cap reached: {settings.NEARBY_SERVICES_MAX_API_CALLS_PER_RUN} SerpApi calls already made this run"
        )
    api_key = os.environ.get("SERPAPI_KEY")
    if not api_key:
        raise NearbyServicesError("SERPAPI_KEY is not set in the environment")

    _api_call_count += 1
    try:
        resp = requests.get(
            SERPAPI_SEARCH_URL,
            params={
                "engine": "google_maps",
                "type": "search",
                "q": query,
                "ll": f"@{lat},{lng},14z",
                "api_key": api_key,
            },
            timeout=settings.NEARBY_SERVICES_TIMEOUT_S,
        )
        resp.raise_for_status()
    except requests.exceptions.Timeout:
        raise NearbyServicesError(f"SerpApi request timed out after {settings.NEARBY_SERVICES_TIMEOUT_S}s")
    except requests.exceptions.RequestException as e:
        raise NearbyServicesError(f"SerpApi request failed: {type(e).__name__}")

    data = resp.json()
    if "error" in data:
        raise NearbyServicesError(f"SerpApi error: {data['error']}")
    return data.get("local_results", [])


# --- Result filtering (fix pass: SerpApi type/types based) -------------------
# Each rule returns an exclusion reason or None. Everything excluded is recorded
# (category, title, reason) in the cache entry's "excluded" list.
GENERIC_NAMES = {"hospital", "clinic", "police", "police station", "fire", "fire station", "fire brigade",
                 "police chowki", "police post", "medical center", "medical centre"}
HOSPITAL_KEEP = ("hospital", "clinic", "medical center", "medical centre", "emergency")
HOSPITAL_REJECT = ("pharmacy", "medical supply", "medical store", "diagnostic", "laborator", "veterinar", "pet ", "animal", "dental")
RAILWAY_MARKERS = ("railway", "grp", "rpf", "government railway police", "railway protection")
FIRE_REJECT_TYPES = ("supplier", "shop", "store", "equipment", "dealer", "extinguisher", "manufacturer", "wholesaler", "distributor")
FIRE_REJECT_NAME = ("enterprises", "equipment", "dealer", "supplier", "shop", "extinguisher", "traders", "agency")
PHONE_PREFERENCE_WINDOW_KM = 0.3


def _types_text(result: dict) -> str:
    return (str(result.get("type") or "") + " " + " ".join(str(t) for t in (result.get("types") or []))).lower()


def exclusion_reason(category: str, result: dict) -> Optional[str]:
    """Why this raw SerpApi result must not be offered as a `category` responder (None = keep)."""
    title = (result.get("title") or "").strip()
    if len(title) < 3 or title.lower() in GENERIC_NAMES:
        return "no usable name" if len(title) < 3 else f"generic name ({title!r}) - not identifiable"
    types, lower_title = _types_text(result), title.lower()
    if category == "hospital":
        if any(k in types or k in lower_title for k in HOSPITAL_REJECT) and not any(k in types for k in ("hospital", "emergency")):
            return f"not a hospital/clinic (type: {types.strip()[:60]})"
        if not any(k in types for k in HOSPITAL_KEEP):
            return f"type is not hospital/clinic (type: {types.strip()[:60]})"
    elif category == "police":
        if "police" not in types:
            return f"type is not police station (type: {types.strip()[:60]})"
        squashed = "".join(ch for ch in lower_title if ch.isalpha())  # catches "G R P" / "G.R.P."
        if any(m in types or m in lower_title for m in RAILWAY_MARKERS) or "grp" in squashed:
            return "railway police (GRP/RPF) excluded for road incidents"
    elif category == "fire":
        if "fire" not in types:
            return f"type is not fire station (type: {types.strip()[:60]})"
        if any(k in types for k in FIRE_REJECT_TYPES) or any(k in lower_title for k in FIRE_REJECT_NAME):
            return f"equipment/supplier, not a fire station (type: {types.strip()[:60]})"
    return None


def rank_services(services: list[dict]) -> list[dict]:
    """Nearest first, except that among results within 300 m of each other (measured from the
    nearest remaining one) those with a phone number come first."""
    remaining = sorted(services, key=lambda s: s["distance_km"])
    ranked = []
    while remaining:
        window = [s for s in remaining if s["distance_km"] - remaining[0]["distance_km"] <= PHONE_PREFERENCE_WINDOW_KM]
        best = sorted(window, key=lambda s: (not s.get("phone"), s["distance_km"]))[0]
        ranked.append(best)
        remaining.remove(best)
    return ranked


def _extract_service(result: dict, category: str, origin_lat: float, origin_lng: float) -> Optional[dict]:
    gps = result.get("gps_coordinates")
    if not gps or gps.get("latitude") is None or gps.get("longitude") is None:
        return None  # no fabricated coordinates -- skip a result SerpApi didn't actually geolocate
    lat, lng = gps["latitude"], gps["longitude"]
    return {
        "title": result.get("title"),
        "category": category,
        "type": result.get("type"),
        "types": result.get("types") or [],
        "address": result.get("address"),
        "phone": result.get("phone"),
        "rating": result.get("rating"),
        "open_state": result.get("open_state"),
        "gps_coordinates": {"latitude": lat, "longitude": lng},
        "place_id": result.get("place_id"),
        "distance_km": round(_haversine_km(origin_lat, origin_lng, lat, lng), 2),
        "type_looks_correct": _looks_like_right_type(category, result),
    }


def _dedupe(services: list[dict]) -> list[dict]:
    seen_place_ids = set()
    out = []
    for s in services:
        pid = s.get("place_id")
        key = pid if pid else (s.get("title"), s.get("address"))
        if key in seen_place_ids:
            continue
        seen_place_ids.add(key)
        out.append(s)
    return out


CATEGORIES = tuple(CATEGORY_QUERIES)
_inflight: dict[str, threading.Event] = {}
_inflight_lock = threading.Lock()
_cache_lock = threading.RLock()


def cell_key(latitude: float, longitude: float) -> str:
    """~100 m grid cell (0.001 deg of latitude is ~111 m, of longitude ~99 m at Jaipur's latitude), so small
    GPS drift reuses the cache and a different place never reuses another place's results."""
    return f"cell:{latitude:.3f},{longitude:.3f}"


def api_calls_made() -> int:
    return _api_call_count


def _cache_with_migration() -> dict:
    """Entries written before the grid change were keyed by camera id; move them to their cell using the
    camera registry (no SerpApi calls). Unknown ids are dropped."""
    cache = _load_cache()
    legacy = [k for k in cache if not k.startswith("cell:")]
    if not legacy:
        return cache
    from api.models.camera import get_camera
    for key in legacy:
        entry = cache.pop(key)
        cam = get_camera(key)
        if cam is not None and cam.latitude is not None:
            cache.setdefault(cell_key(cam.latitude, cam.longitude), entry)
    _save_cache(cache)
    return cache


def lookup_cached(latitude: float, longitude: float) -> Optional[dict]:
    """Complete, fresh cache entry for this cell (all categories) or None. Never touches the network."""
    with _cache_lock:
        entry = _cache_with_migration().get(cell_key(latitude, longitude))
    if entry and _cache_entry_fresh(entry) and all(c in entry.get("services", {}) for c in CATEGORIES):
        return {"source": "cache", "cached_at": entry["cached_at"], "services": entry["services"], "excluded": entry.get("excluded")}
    return None


def get_nearby_services(camera_id: str, latitude: float, longitude: float, place_text: str,
                         force_refresh: bool = False) -> dict:
    """Returns {category: [services...]} for hospital/police/fire, nearest-first (phone preferred), keyed by
    ~100 m grid cell. A fresh complete entry is a cache hit; otherwise only the missing categories are fetched
    (SerpApi call cap applies). One lookup per cell at a time (prefetch and incident share it). Raises
    NearbyServicesError on a real failure -- never fabricated data, never another cell's results."""
    key = cell_key(latitude, longitude)
    if not force_refresh:
        hit = lookup_cached(latitude, longitude)
        if hit:
            return hit
    with _inflight_lock:
        waiting_on = _inflight.get(key)
        if waiting_on is None:
            _inflight[key] = threading.Event()
    if waiting_on is not None:  # someone else is already looking this cell up
        waiting_on.wait(timeout=60)
        hit = lookup_cached(latitude, longitude)
        if hit:
            return hit
        raise NearbyServicesError("lookup for this location failed or timed out")
    try:
        return _fetch_cell(key, latitude, longitude, place_text, force_refresh)
    finally:
        with _inflight_lock:
            _inflight.pop(key).set()


def _fetch_cell(key: str, latitude: float, longitude: float, place_text: str, force_refresh: bool) -> dict:
    with _cache_lock:
        cache = _cache_with_migration()
    entry = cache.get(key) if not force_refresh else None
    fresh = bool(entry and _cache_entry_fresh(entry))
    result = dict(entry["services"]) if fresh else {}
    excluded = list(entry.get("excluded") or []) if fresh else []
    city = _city_from_place_text(place_text)
    errors: dict[str, str] = {}

    for category, query_word in CATEGORY_QUERIES.items():
        if category in result:
            continue
        query = f"{query_word} {city}".strip()
        try:
            raw_results = _query_serpapi(query, latitude, longitude)
        except NearbyServicesError as e:
            errors[category] = str(e)
            continue
        kept_raw = []
        for r in raw_results:
            reason = exclusion_reason(category, r)
            if reason:
                excluded.append({"category": category, "title": (r.get("title") or "").strip() or None, "reason": reason})
            else:
                kept_raw.append(r)
        extracted = [s for s in (_extract_service(r, category, latitude, longitude) for r in kept_raw) if s is not None]
        result[category] = rank_services(_dedupe(extracted))[:settings.NEARBY_SERVICES_KEEP_TOP_N]

    if not result and errors:
        raise NearbyServicesError(f"all categories failed: {errors}")

    cached_at = datetime.now(timezone.utc).isoformat()
    with _cache_lock:
        cache = _cache_with_migration()
        cache[key] = {"cached_at": cached_at, "services": result, "errors": errors or None, "excluded": excluded}
        _save_cache(cache)
    return {"source": "live", "cached_at": cached_at, "services": result, "errors": errors or None, "excluded": excluded}


def warm_async(latitude: float, longitude: float, place_text: str) -> None:
    """Background prefetch for a position's cell (phone start-up, or the phone moved to a new cell). Respects the
    SerpApi cap (a capped/failed lookup is simply a later cache miss) and never raises."""
    def run():
        try:
            if lookup_cached(latitude, longitude) is None:
                get_nearby_services("prefetch", latitude, longitude, place_text)
        except Exception:
            pass
    threading.Thread(target=run, name="nearby-prefetch", daemon=True).start()
