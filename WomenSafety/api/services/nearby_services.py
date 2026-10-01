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
    return parts[-1] if parts else place_text.strip()


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


def _extract_service(result: dict, category: str, origin_lat: float, origin_lng: float) -> Optional[dict]:
    gps = result.get("gps_coordinates")
    if not gps or gps.get("latitude") is None or gps.get("longitude") is None:
        return None  # no fabricated coordinates -- skip a result SerpApi didn't actually geolocate
    lat, lng = gps["latitude"], gps["longitude"]
    return {
        "title": result.get("title"),
        "category": category,
        "type": result.get("type"),
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


def get_nearby_services(camera_id: str, latitude: float, longitude: float, place_text: str,
                         force_refresh: bool = False) -> dict:
    """Returns {category: [services...]} for hospital/police/fire,
    nearest NEARBY_SERVICES_KEEP_TOP_N each, from cache if fresh (TTL,
    default 30 days) unless force_refresh. Raises NearbyServicesError on
    a real failure (never returns fabricated data as a fallback)."""
    cache = _load_cache()
    cached = cache.get(camera_id)
    if cached and not force_refresh and _cache_entry_fresh(cached):
        return {"source": "cache", "cached_at": cached["cached_at"], "services": cached["services"]}

    city = _city_from_place_text(place_text)
    result: dict[str, list[dict]] = {}
    errors: dict[str, str] = {}

    for category, query_word in CATEGORY_QUERIES.items():
        query = f"{query_word} {city}"
        try:
            raw_results = _query_serpapi(query, latitude, longitude)
        except NearbyServicesError as e:
            errors[category] = str(e)
            continue
        extracted = [
            s for s in (
                _extract_service(r, category, latitude, longitude) for r in raw_results
            ) if s is not None
        ]
        extracted = _dedupe(extracted)
        extracted.sort(key=lambda s: s["distance_km"])
        result[category] = extracted[:settings.NEARBY_SERVICES_KEEP_TOP_N]

    if not result and errors:
        # Every category failed -- a real error, not an empty-but-valid result.
        raise NearbyServicesError(f"all categories failed: {errors}")

    cached_at = datetime.now(timezone.utc).isoformat()
    cache[camera_id] = {"cached_at": cached_at, "services": result, "errors": errors or None}
    _save_cache(cache)

    return {"source": "live", "cached_at": cached_at, "services": result, "errors": errors or None}
