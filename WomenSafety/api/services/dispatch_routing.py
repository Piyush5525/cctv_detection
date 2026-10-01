"""Build a display-only dispatch plan for a confirmed CCTV incident.

The plan selects the nearest real lookup result for each service required by
the incident category.  It is deliberately *not* a contact plan: discovered
service phone numbers are retained only as lookup data and are never dialed.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

from api.core.config import settings
from api.services.nearby_services import _haversine_km

MAPBOX_DIRECTIONS_URL = "https://api.mapbox.com/directions/v5/mapbox/driving"
FALLBACK_SPEED_KMH = 30.0

# Required responders are intentionally explicit and reviewable.  The order
# is the operator-facing priority, not an instruction to contact a service.
REQUIRED_SERVICES = {
    "road_accident": ("hospital", "police", "fire"),
    "fire": ("fire", "hospital", "police"),
    "assault": ("police", "hospital"),
    "snatching": ("police",),
    "fall": ("hospital",),
    "women_safety": ("police", "hospital"),
    "other": ("police", "hospital"),
}


def _load_cache() -> dict:
    path = settings.DISPATCH_ROUTE_CACHE_PATH
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    path = settings.DISPATCH_ROUTE_CACHE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def _fresh(entry: dict) -> bool:
    try:
        cached_at = datetime.fromisoformat(entry["cached_at"])
        return (datetime.now(timezone.utc) - cached_at).total_seconds() < settings.DISPATCH_ROUTE_CACHE_TTL_DAYS * 86400
    except Exception:
        return False


def _fallback(origin_lat: float, origin_lng: float, dest_lat: float, dest_lng: float) -> dict:
    distance = _haversine_km(origin_lat, origin_lng, dest_lat, dest_lng)
    return {
        "route_source": "straight_line_fallback",
        "distance_km": round(distance, 2),
        "eta_minutes": round(distance / FALLBACK_SPEED_KMH * 60, 1),
        "geometry": {"type": "LineString", "coordinates": [[origin_lng, origin_lat], [dest_lng, dest_lat]]},
        "note": f"Straight-line estimate at {FALLBACK_SPEED_KMH:g} km/h; Mapbox driving route unavailable.",
    }


def route_to_service(origin_lat: float, origin_lng: float, service: dict) -> dict:
    """Return a cached Mapbox driving route, or an explicitly labelled fallback.

    A missing token, timeout, invalid response, or map API failure must never
    fabricate a road route: callers receive only the geometric fallback.
    """
    gps = service.get("gps_coordinates") or {}
    dest_lat, dest_lng = gps.get("latitude"), gps.get("longitude")
    if dest_lat is None or dest_lng is None:
        return {"route_source": "unavailable", "reason": "service has no coordinates"}
    key = f"{origin_lat:.5f},{origin_lng:.5f}:{dest_lat:.5f},{dest_lng:.5f}"
    cache = _load_cache()
    cached = cache.get(key)
    if cached and _fresh(cached):
        return {**cached["route"], "cached": True}

    fallback = _fallback(origin_lat, origin_lng, dest_lat, dest_lng)
    token = os.environ.get("MAPBOX_TOKEN")
    if not token:
        return fallback
    try:
        response = requests.get(
            f"{MAPBOX_DIRECTIONS_URL}/{origin_lng},{origin_lat};{dest_lng},{dest_lat}",
            params={"access_token": token, "geometries": "geojson", "overview": "full"},
            timeout=settings.MAPBOX_DIRECTIONS_TIMEOUT_S,
        )
        response.raise_for_status()
        route = response.json().get("routes", [])[0]
        route_data = {
            "route_source": "mapbox_driving",
            "distance_km": round(float(route["distance"]) / 1000, 2),
            "eta_minutes": round(float(route["duration"]) / 60, 1),
            "geometry": route["geometry"],
        }
        cache[key] = {"cached_at": datetime.now(timezone.utc).isoformat(), "route": route_data}
        _save_cache(cache)
        return route_data
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError):
        return fallback


def build_dispatch_plan(category: str, latitude: float, longitude: float, services: dict) -> dict:
    """Select the nearest result for each required category and add route data."""
    required = list(REQUIRED_SERVICES.get(category, REQUIRED_SERVICES["other"]))
    assignments = []
    for service_category in required:
        candidates = (services or {}).get(service_category, [])
        if not candidates:
            assignments.append({"service_category": service_category, "status": "unavailable", "reason": "no lookup result"})
            continue
        chosen = min(candidates, key=lambda item: item.get("distance_km", float("inf")))
        assignments.append({
            "service_category": service_category,
            "status": "available",
            "service": chosen,
            "route": route_to_service(latitude, longitude, chosen),
        })
    return {
        "category": category,
        "required_services": required,
        "assignments": assignments,
        "contact_policy": "display_only_never_auto_dial_discovered_numbers",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
