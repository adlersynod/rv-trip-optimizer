"""
geocoder.py — Nominatim (OSM) geocoding wrapper
Uses OSM Nominatim for free, no-API-key geocoding and reverse geocoding.
"""

import requests
from typing import Optional, Tuple

NOMINATIM_URL = "https://nominatim.openstreetmap.org"
USER_AGENT = "RV-Trip-Optimizer/1.0 (personal use; adlersynod)"

def _nominatim_headers() -> dict:
    return {"User-Agent": USER_AGENT}


def geocode_address(address: str, limit: int = 1) -> Optional[dict]:
    """
    Geocode a free-text address to (lat, lon, display_name).
    Returns dict with keys: lat, lon, display_name, raw (full response)
    or None if not found.
    """
    params = {
        "q": address,
        "format": "json",
        "limit": limit,
        "addressdetails": 1,
    }
    try:
        resp = requests.get(
            f"{NOMINATIM_URL}/search",
            params=params,
            headers=_nominatim_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data:
            return None
        result = data[0]
        return {
            "lat": float(result["lat"]),
            "lon": float(result["lon"]),
            "display_name": result.get("display_name", ""),
            "raw": result,
        }
    except Exception as e:
        print(f"[geocoder] Geocoding failed for '{address}': {e}")
        return None


def reverse_geocode(lat: float, lon: float) -> Optional[dict]:
    """
    Reverse geocode (lat, lon) to a display name and address components.
    Returns dict with keys: display_name, city, state, country, raw.
    """
    params = {
        "lat": lat,
        "lon": lon,
        "format": "json",
        "addressdetails": 1,
    }
    try:
        resp = requests.get(
            f"{NOMINATIM_URL}/reverse",
            params=params,
            headers=_nominatim_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        addr = data.get("address", {})
        return {
            "display_name": data.get("display_name", ""),
            "city": addr.get("city") or addr.get("town") or addr.get("village", ""),
            "state": addr.get("state", ""),
            "country": addr.get("country", ""),
            "raw": addr,
        }
    except Exception as e:
        print(f"[geocoder] Reverse geocoding failed for ({lat}, {lon}): {e}")
        return None


def distance_haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Haversine distance between two points in miles.
    """
    from math import radians, sin, cos, sqrt, atan2
    R = 3958.8  # Earth radius in miles
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c
