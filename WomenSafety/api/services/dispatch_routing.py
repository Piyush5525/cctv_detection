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

from api.core.config import DISPATCH_RULES, SERVICE_LABELS, SERVICE_LOOKUP_KEY, required_services, settings
from api.services.nearby_services import _haversine_km

MAPBOX_DIRECTIONS_URL = "https://api.mapbox.com/directions/v5/mapbox/driving"
FALLBACK_SPEED_KMH = 30.0

# Required responders per category now live in api/core/config.py (DISPATCH_RULES),
# primary first. Kept as an alias for older imports.
REQUIRED_SERVICES = DISPATCH_RULES


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


MAX_ALTERNATIVES = 2


def _brief(service: dict) -> dict:
    return {k: service.get(k) for k in ("title", "phone", "address", "distance_km", "gps_coordinates") if k in service}


def build_dispatch_plan(category: str, latitude: float, longitude: float, services: dict) -> dict:
    """One assignment per service type required for `category` (DISPATCH_RULES), primary
    first. A missing type is reported as unavailable; it is NEVER replaced by another type.
    The first candidate is the nearest/best-ranked one and gets a route; up to two more
    are kept as `alternatives` (markers only). Nothing is fabricated: no lookup result,
    no assignment."""
    required = list(required_services(category))
    assignments = []
    for index, service_type in enumerate(required):
        role = "primary" if index == 0 else "secondary"
        candidates = (services or {}).get(SERVICE_LOOKUP_KEY[service_type], [])
        if not candidates:
            assignments.append({"service_category": service_type, "role": role, "status": "unavailable",
                                "reason": f"No {SERVICE_LABELS[service_type]} found nearby"})
            continue
        chosen = candidates[0]  # lookup order is already nearest-first with the phone-number preference applied
        assignments.append({
            "service_category": service_type,
            "role": role,
            "status": "available",
            "service": chosen,
            "route": route_to_service(latitude, longitude, chosen),
            "alternatives": [_brief(c) for c in candidates[1:1 + MAX_ALTERNATIVES]],
        })
    return {
        "category": category,
        "required_services": required,
        "assignments": assignments,
        "contact_policy": "display_only_never_auto_dial_discovered_numbers",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def conform_plan(category: str, plan: dict) -> dict:
    """Plans stored before the rules table existed (or built by hand) are brought in line
    with DISPATCH_RULES when they leave the API: old "fire" -> "fire_station", types the
    category does not need are dropped, roles set, and a missing required type is shown
    as unavailable. Plans without assignments (lookup error / pending) pass through."""
    if not plan or not plan.get("assignments"):
        return plan
    required = list(required_services(category))
    by_type = {}
    for item in plan["assignments"]:
        key = "fire_station" if item.get("service_category") == "fire" else item.get("service_category")
        by_type.setdefault(key, {**item, "service_category": key})
    assignments = []
    for index, service_type in enumerate(required):
        role = "primary" if index == 0 else "secondary"
        item = by_type.get(service_type) or {"service_category": service_type, "status": "unavailable",
                                              "reason": f"No {SERVICE_LABELS[service_type]} found nearby"}
        assignments.append({**item, "role": role})
    return {**plan, "required_services": required, "assignments": assignments}
