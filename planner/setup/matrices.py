"""
NumPy matrix computations: haversine, energy, travel time.

Adaptive velocity model:
    Energy -> ALWAYS at eco speed (70 km/h, multiplier 1.0)
              This maximizes range and ensures all physically possible
              routes are feasible. The system automatically "reduces speed"
              to reach distant stations.

    Time   -> At cruise speed (90 km/h) or TomTom real-world data.
              This gives realistic travel time estimates for the Z-score.

    Weather -> Applies a time multiplier (does NOT affect energy).
"""
from __future__ import annotations

import numpy as np

from planner.setup.config import BASE_VELOCITY_KMH, CRUISE_VELOCITY_KMH
from planner.setup.routing_cache import load_routes_bulk, _round_coord
from planner.setup.tomtom import route_summary
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
    live_traffic: bool = False,
    weather_squares: list[WeatherSquare] | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Calculate Energy (%), Time (min), and Real-Road-KM matrices.

    Adaptive velocity model:
      - ENERGY is always computed at eco speed (70 km/h, multiplier 1.0)
        to maximize range and ensure route feasibility.
      - TIME is computed at cruise speed (90 km/h) or TomTom real-world data.
      - If even eco speed can't handle an edge (>99% battery), mark unreachable.
      - Weather penalties apply to TIME only (not energy).

    Returns:
        (energy_mat, time_mat, road_km_mat)
    """
    n = dist_mat.shape[0]
    energy_mat = np.zeros((n, n), dtype=float)
    time_mat = np.zeros((n, n), dtype=float)
    road_km_mat = np.zeros((n, n), dtype=float)

    cache_hits = 0
    api_hits = 0
    api_rate_limit_hit = False

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
            
            # Try to get exact real-world route if coordinates are provided
            if coords is not None:
                lat1, lon1 = coords[i]
                lat2, lon2 = coords[j]
                rlat1, rlon1 = _round_coord(lat1), _round_coord(lon1)
                rlat2, rlon2 = _round_coord(lat2), _round_coord(lon2)
                
                # Live traffic: hit API directly (rare usage)
                if live_traffic and api_key and not api_rate_limit_hit:
                    try:
                        km, mins = route_summary(lat1, lon1, lat2, lon2, api_key, use_cache=False, live_traffic=True)
                        if km != float('inf'):
                            dist_km = km
                            base_time_min = mins
                            api_hits += 1
                    except RuntimeError as e:
                        if "403" in str(e) or "429" in str(e):
                            print(f"\n  [!] {e} Disabling live API for remainder of this leg.")
                            api_rate_limit_hit = True
                    except Exception:
                        pass
                
                # Standard path: fast dict lookup from bulk-loaded cache
                if base_time_min is None:
                    key = (rlat1, rlon1, rlat2, rlon2)
                    cached = route_dict.get(key)
                    if cached is not None:
                        dist_km = cached[0]
                        base_time_min = cached[1]
                        cache_hits += 1

            road_km_mat[i, j] = dist_km
                        
            if dist_km < 1e-3:
                continue

            # ── ENERGY: always at eco speed (70 km/h) ──
            # This ensures maximum range and feasibility.
            # No multiplier at eco speed (multiplier = 1.0).
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
        fallback_count = total_edges - cache_hits - api_hits
        print(f"       -> Road data: {cache_hits}/{total_edges} from DB cache, "
              f"{api_hits} live API, {fallback_count} haversine fallback")

    return energy_mat, time_mat, road_km_mat
