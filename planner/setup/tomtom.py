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


def geocode(query: str, api_key: str) -> tuple[float, float]:
    """Geocode a location string via TomTom.  Returns (lat, lon)."""
    q = quote(query.strip(), safe="")
    url = f"{TOMTOM_GEOCODE_BASE}/{q}.json"
    params = {"key": api_key, "countrySet": "TR", "limit": 1}
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    results = r.json().get("results") or []
    if not results:
        raise RuntimeError(f"No geocode results for: {query!r}")
    pos = results[0].get("position", {})
    lat, lon = pos.get("lat"), pos.get("lon")
    if lat is None or lon is None:
        raise RuntimeError(f"Geocode missing position for: {query!r}")
    return float(lat), float(lon)


def route_summary(
    lat_o: float, lon_o: float, lat_d: float, lon_d: float, api_key: str,
) -> tuple[float, float]:
    """Get driving route summary from TomTom.  Returns (road_km, drive_min)."""
    locs = f"{lat_o},{lon_o}:{lat_d},{lon_d}"
    url = f"https://api.tomtom.com/routing/1/calculateRoute/{locs}/json"
    params = {"key": api_key, "routeRepresentation": "summaryOnly", "travelMode": "car"}
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    routes = r.json().get("routes") or []
    if not routes:
        raise RuntimeError("TomTom returned no routes.")
    s = routes[0].get("summary", {})
    km = float(s.get("lengthInMeters", 0)) / 1000.0
    mins = float(s.get("travelTimeInSeconds", 0)) / 60.0
    return km, mins
