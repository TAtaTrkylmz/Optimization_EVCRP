"""
NumPy matrix computations: haversine, energy, travel time.

Adaptive velocity model with per-segment speed gene:
    Energy -> Computed using the EA's speed_factor gene per segment.
              E = base_consumption × (v / v_eco)^α
              where v = base_velocity × speed_factor, v_eco = 70 km/h,
              and α = VELOCITY_EXPONENT (1.6, aerodynamic drag).

    Time   -> Computed from the chosen speed, or TomTom real-world data
              if cached (whichever gives the more accurate estimate).

    Weather -> Applies a time multiplier (does NOT affect energy).

    Speed limits -> Derived from cached TomTom data (road_km / drive_min).
                    Max allowed speed = speed_limit × SPEED_LIMIT_HEADROOM (1.10).
                    Stored in speed_limit_mat for the EA to use as a ceiling.
"""
from __future__ import annotations

import numpy as np

from planner.setup.config import (
    BASE_VELOCITY_KMH, CRUISE_VELOCITY_KMH,
    SPEED_FACTOR_MAX, SPEED_LIMIT_HEADROOM,
)
from planner.setup.routing_cache import load_routes_bulk, _round_coord
from planner.setup.logger import log
from api.mocker import WeatherSquare, get_segment_weather_penalty


def haversine_matrix(coords: np.ndarray) -> np.ndarray:
    """Vectorised pairwise haversine distances (km)."""
    lat = np.radians(coords[:, 0])
    lon = np.radians(coords[:, 1])
    dlat = lat[:, None] - lat[None, :]
    dlon = lon[:, None] - lon[None, :]
    h = (np.sin(dlat / 2) ** 2
         + np.cos(lat[:, None]) * np.cos(lat[None, :]) * np.sin(dlon / 2) ** 2)
    return 2 * 6371.0 * np.arcsin(np.minimum(1.0, np.sqrt(h)))


def build_cost_matrices(
    dist_mat: np.ndarray,
    road_factor: float,
    consumption_kwh_per_100km: float,
    battery_capacity_kwh: float,
    target_velocity_kmh: float = CRUISE_VELOCITY_KMH,
    base_velocity_kmh: float = BASE_VELOCITY_KMH,
    coords: list[tuple[float, float]] = None,
    api_key: str = None,
    live_traffic: bool = False,      # kept for call-site compat, always ignored
    weather_squares: list[WeatherSquare] | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Calculate Energy-at-eco (%), Time (min), Road-KM, and Speed-Limit matrices.

    The energy_mat now contains the BASE energy at eco speed (speed_factor=1.0).
    The EA solver will scale it using the speed_factor gene per segment.

    Returns:
        (energy_mat, time_mat, road_km_mat, speed_limit_mat)

        speed_limit_mat[i,j] = max allowed speed_factor for edge (i,j).
        Derived from cached TomTom data: (avg_speed / BASE_VELOCITY) × HEADROOM.
        For edges without cached data, defaults to SPEED_FACTOR_MAX.
    """
    n = dist_mat.shape[0]
    energy_mat = np.zeros((n, n), dtype=float)
    time_mat = np.zeros((n, n), dtype=float)
    road_km_mat = np.zeros((n, n), dtype=float)
    speed_limit_mat = np.full((n, n), SPEED_FACTOR_MAX, dtype=float)

    cache_hits = 0

    # ── Bulk-load cached routes in ONE DB connection ──
    route_dict: dict = {}
    if coords is not None:
        route_dict = load_routes_bulk(coords)

    for i in range(n):
        for j in range(n):
            if i == j:
                continue
                
            # Default to haversine + road_factor
            dist_km = dist_mat[i, j] * road_factor
            base_time_min = None
            
            # Try to get exact real-world route from cache
            if coords is not None:
                lat1, lon1 = coords[i]
                lat2, lon2 = coords[j]
                rlat1, rlon1 = _round_coord(lat1), _round_coord(lon1)
                rlat2, rlon2 = _round_coord(lat2), _round_coord(lon2)
                
                key = (rlat1, rlon1, rlat2, rlon2)
                cached = route_dict.get(key)
                if cached is not None:
                    dist_km = cached[0]
                    base_time_min = cached[1]
                    cache_hits += 1
                    
                    # Derive speed limit from cached data
                    if base_time_min > 0.01 and dist_km > 0.01:
                        avg_speed_kmh = dist_km / (base_time_min / 60.0)
                        speed_limit_factor = (avg_speed_kmh / base_velocity_kmh) * SPEED_LIMIT_HEADROOM
                        speed_limit_mat[i, j] = max(speed_limit_factor, 0.7)  # never below min

            road_km_mat[i, j] = dist_km
                        
            if dist_km < 1e-3:
                continue

            # ── ENERGY: at eco speed (speed_factor=1.0) ──
            # The EA solver will scale this by (speed_factor)^VELOCITY_EXPONENT
            base_kwh = (dist_km / 100.0) * consumption_kwh_per_100km
            energy_pct = (base_kwh / battery_capacity_kwh) * 100.0
                
            if energy_pct > 99.0:
                # Even at eco speed, this edge is physically unreachable
                energy_mat[i, j] = 1000.0
                time_mat[i, j] = 10000.0
                continue
                
            energy_mat[i, j] = energy_pct
            
            # ── TIME: at cruise speed (90 km/h) or TomTom real-world ──
            if base_time_min is not None:
                # Trust real-world time from TomTom/cache
                time_mat[i, j] = base_time_min
            else:
                # Use cruise speed for time estimation
                time_mat[i, j] = (dist_km / target_velocity_kmh) * 60.0

            # Apply weather penalty to time only
            if weather_squares and coords is not None:
                wp = get_segment_weather_penalty(
                    coords[i][0], coords[i][1],
                    coords[j][0], coords[j][1],
                    weather_squares,
                )
                time_mat[i, j] *= wp

    if coords is not None:
        total_edges = n * (n - 1)
        fallback_count = total_edges - cache_hits
        log.step(f"Road data: {cache_hits}/{total_edges} from DB cache, "
                 f"{fallback_count} haversine fallback")

    return energy_mat, time_mat, road_km_mat, speed_limit_mat
