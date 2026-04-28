"""
TomTom API helpers: geocoding and route summary.
"""
from __future__ import annotations

import os
import sys
from urllib.parse import quote

import requests

from planner.setup.config import REPO_ROOT, TOMTOM_GEOCODE_BASE


def load_api_key() -> str:
    """Read TOMTOM_API_KEY from .env file or environment."""
    env_path = REPO_ROOT / ".env"
    if env_path.is_file():
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))
    key = os.environ.get("TOMTOM_API_KEY", "").strip()
    if not key:
        print("Set TOMTOM_API_KEY in .env at repo root.")
        sys.exit(1)
    return key


import time
from planner.setup.routing_cache import get_route_from_cache, save_route_to_cache, get_geocode_from_cache, save_geocode_to_cache

def geocode(query: str, api_key: str) -> tuple[float, float]:
    """Geocode a location string via TomTom.  Returns (lat, lon)."""
    cached = get_geocode_from_cache(query)
    if cached is not None:
        return cached

    q = quote(query.strip(), safe="")
    url = f"{TOMTOM_GEOCODE_BASE}/{q}.json"
    params = {"key": api_key, "countrySet": "TR", "limit": 1}
    
    try:
        r = requests.get(url, params=params, timeout=60)
        if r.status_code in (403, 429):
            raise RuntimeError(f"API limit or quota exceeded ({r.status_code}). Stop.")
        r.raise_for_status()
    except requests.exceptions.HTTPError as e:
        status_code = getattr(e.response, "status_code", None)
        if status_code in (403, 429):
            raise RuntimeError(f"API limit or quota exceeded ({status_code}). Stop.") from e
        raise

    results = r.json().get("results") or []
    if not results:
        raise RuntimeError(f"No geocode results for: {query!r}")
    pos = results[0].get("position", {})
    lat, lon = pos.get("lat"), pos.get("lon")
    if lat is None or lon is None:
        raise RuntimeError(f"Geocode missing position for: {query!r}")
        
    save_geocode_to_cache(query, float(lat), float(lon))
    return float(lat), float(lon)

def route_summary(
    lat_o: float, lon_o: float, lat_d: float, lon_d: float, api_key: str,
    use_cache: bool = True, live_traffic: bool = False
) -> tuple[float, float]:
    """Get driving route summary from TomTom.  Returns (road_km, drive_min)."""
    if use_cache and not live_traffic:
        cached = get_route_from_cache(lat_o, lon_o, lat_d, lon_d)
        if cached is not None:
            return cached

    locs = f"{lat_o},{lon_o}:{lat_d},{lon_d}"
    url = f"https://api.tomtom.com/routing/1/calculateRoute/{locs}/json"
    
    params = {
        "key": api_key, 
        "routeRepresentation": "summaryOnly", 
        "travelMode": "car"
    }
    
    if live_traffic:
        params["traffic"] = "true"
        params["computeTravelTimeFor"] = "all"
        
    try:
        r = requests.get(url, params=params, timeout=60)
        
        if r.status_code in (403, 429):
            raise RuntimeError(f"API limit or quota exceeded ({r.status_code}). Stop.")
            
        r.raise_for_status()
    except requests.exceptions.HTTPError as e:
        status_code = getattr(e.response, "status_code", None)
        if status_code in (403, 429):
            raise RuntimeError(f"API limit or quota exceeded ({status_code}). Stop.") from e
        raise
        
    routes = r.json().get("routes") or []
    if not routes:
        return float('inf'), float('inf')
        
    s = routes[0].get("summary", {})
    km = float(s.get("lengthInMeters", 0)) / 1000.0
    
    if live_traffic and "liveTrafficIncidentsTravelTimeInSeconds" in s:
        mins = float(s["liveTrafficIncidentsTravelTimeInSeconds"]) / 60.0
    else:
        mins = float(s.get("travelTimeInSeconds", 0)) / 60.0

    if not live_traffic:
        save_route_to_cache(lat_o, lon_o, lat_d, lon_d, km, mins)
        
    return km, mins


def route_with_geometry(
    lat_o: float, lon_o: float, lat_d: float, lon_d: float, api_key: str,
) -> list[tuple[float, float]]:
    """Fetch route geometry (polyline) between two points.
    
    Checks cache first. If not cached, fetches from TomTom API and saves.
    Returns list of (lat, lon) points tracing the road.
    Falls back to straight line if API fails.
    """
    from planner.setup.routing_cache import get_geometry_from_cache, save_geometry_to_cache
    
    # Check cache first
    cached = get_geometry_from_cache(lat_o, lon_o, lat_d, lon_d)
    if cached is not None:
        return cached
    
    # Fetch from API (full route, not summaryOnly)
    locs = f"{lat_o},{lon_o}:{lat_d},{lon_d}"
    url = f"https://api.tomtom.com/routing/1/calculateRoute/{locs}/json"
    params = {"key": api_key, "travelMode": "car"}
    
    try:
        r = requests.get(url, params=params, timeout=60)
        if r.status_code in (403, 429):
            print(f"  [!] API limit hit fetching geometry, using straight line.")
            return [(lat_o, lon_o), (lat_d, lon_d)]
        r.raise_for_status()
    except Exception:
        return [(lat_o, lon_o), (lat_d, lon_d)]
    
    routes = r.json().get("routes") or []
    if not routes:
        return [(lat_o, lon_o), (lat_d, lon_d)]
    
    # Extract geometry points from all legs
    geometry = []
    for leg in routes[0].get("legs", []):
        for pt in leg.get("points", []):
            geometry.append((pt["latitude"], pt["longitude"]))
    
    if not geometry:
        return [(lat_o, lon_o), (lat_d, lon_d)]
    
    # Cache for future use
    save_geometry_to_cache(lat_o, lon_o, lat_d, lon_d, geometry)
    
    # Also update summary data if we have it
    s = routes[0].get("summary", {})
    km = float(s.get("lengthInMeters", 0)) / 1000.0
    mins = float(s.get("travelTimeInSeconds", 0)) / 60.0
    save_route_to_cache(lat_o, lon_o, lat_d, lon_d, km, mins, geometry)
    
    return geometry
