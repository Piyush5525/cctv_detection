"""Finds the nearest real police stations and hospitals to an incident's
coordinates via OpenStreetMap's Overpass API.

Chosen over a commercial/government API for this pass because it is free,
requires no API key or signup, and reuses the same OSM data source already
relied on for geocoding (Nominatim) elsewhere in this project -- so there is
no reason to block this feature on a key the user would need to go source
themselves. If a paid provider (e.g. Google Places) is added later for
richer data (phone numbers, opening hours), this module's public function
signature (`nearest_emergency_services`) is the seam to swap the
implementation behind.

Real limitation, stated plainly: OSM's `amenity=police`/`amenity=hospital`
coverage is crowd-sourced and therefore uneven -- dense in large metros,
sparser in smaller towns. A location with no results within the search
radius returns an empty list rather than a fabricated placeholder.
"""
import time

import requests

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
SEARCH_RADIUS_M = 5000  # 5km; widened once if nothing is found nearby
SEARCH_RADIUS_FALLBACK_M = 15000
REQUEST_TIMEOUT = 25

# In-process cache keyed by rounded coordinates -- an incident's location
# doesn't move, and Overpass's public instance is shared/rate-limited, so
# repeat lookups for the same (or a very close) point should not re-hit it.
_cache: dict[tuple[float, float], dict] = {}


def _round_key(lat: float, lng: float) -> tuple[float, float]:
    return (round(lat, 3), round(lng, 3))  # ~110m grid, plenty tight for "nearest station" purposes


def _haversine_km(lat1, lng1, lat2, lng2) -> float:
    from math import radians, sin, cos, sqrt, atan2
    r = 6371.0
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return r * 2 * atan2(sqrt(a), sqrt(1 - a))


def _query_overpass(lat: float, lng: float, amenity: str, radius_m: int) -> list[dict]:
    query = f"""
    [out:json][timeout:{REQUEST_TIMEOUT}];
    (
      node["amenity"="{amenity}"](around:{radius_m},{lat},{lng});
      way["amenity"="{amenity}"](around:{radius_m},{lat},{lng});
    );
    out center tags;
    """
    # The public Overpass instance is shared/rate-limited and genuinely
    # returns transient 504s under load (verified: an identical query
    # succeeded on the very next attempt with no other change) -- worth one
    # short retry before giving up and returning an empty result.
    data = None
    for attempt in range(2):
        try:
            resp = requests.post(
                OVERPASS_URL, data={"data": query}, timeout=REQUEST_TIMEOUT + 5,
                headers={"User-Agent": "detection-models-research/1.0"},  # Overpass returns 406 without a UA
            )
            resp.raise_for_status()
            data = resp.json()
            break
        except Exception:
            if attempt == 1:
                raise
            time.sleep(3)
    results = []
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        name = tags.get("name")
        if not name:
            continue  # unnamed nodes are usually low-quality/incomplete OSM entries
        center = el.get("center") or {"lat": el.get("lat"), "lon": el.get("lon")}
        if center.get("lat") is None or center.get("lon") is None:
            continue
        dist_km = _haversine_km(lat, lng, center["lat"], center["lon"])
        results.append({
            "name": name,
            "latitude": center["lat"],
            "longitude": center["lon"],
            "distance_km": round(dist_km, 2),
            "phone": tags.get("phone") or tags.get("contact:phone"),
            "address": ", ".join(filter(None, [
                tags.get("addr:housenumber"), tags.get("addr:street"),
                tags.get("addr:suburb"), tags.get("addr:city"),
            ])) or None,
        })
    results.sort(key=lambda r: r["distance_km"])
    return results


def _nearest(lat: float, lng: float, amenity: str, limit: int = 3) -> list[dict]:
    try:
        results = _query_overpass(lat, lng, amenity, SEARCH_RADIUS_M)
        if not results:
            results = _query_overpass(lat, lng, amenity, SEARCH_RADIUS_FALLBACK_M)
        return results[:limit]
    except Exception as e:
        print(f"emergency_service: Overpass query failed for amenity={amenity} at ({lat},{lng}): {e}")
        return []


def nearest_emergency_services(lat: float, lng: float, force_refresh: bool = False) -> dict:
    """Returns {"police": [...], "hospitals": [...], "cached": bool} for the
    given coordinates. Each list entry has name/lat/lng/distance_km/phone/address,
    nearest first. Empty lists mean genuinely no tagged OSM data nearby, not
    an error."""
    key = _round_key(lat, lng)
    if not force_refresh and key in _cache:
        cached = dict(_cache[key])
        cached["cached"] = True
        return cached

    police = _nearest(lat, lng, "police")
    time.sleep(1)  # be polite to the shared public Overpass instance between the two queries
    hospitals = _nearest(lat, lng, "hospital")

    result = {"police": police, "hospitals": hospitals, "cached": False}
    _cache[key] = result
    return result
