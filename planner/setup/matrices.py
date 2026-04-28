"""
NumPy matrix computations: haversine, energy, travel time.

The energy matrix now accepts a consumption_multiplier from the
velocity model (see config.py for the formula).
"""
from __future__ import annotations

import numpy as np

from planner.setup.routing_cache import load_routes_bulk, _round_coord
from planner.setup.tomtom import route_summary


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
    target_velocity_kmh: float,
    base_velocity_kmh: float = 70.0,
    coords: list[tuple[float, float]] = None,
    api_key: str = None,
    live_traffic: bool = False
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Calculate Energy (%), Time (min), and Real-Road-KM matrices.

    This implements "Dynamic Eco-Fallback" to completely untangle User Preferences from
    Topological Feasibility. 
      1. Default to Target Velocity (derived from w-time preference).
      2. If target velocity causes Energy Requirement > 100% capacity, drop the speed
         down to safe Eco Speed (70 km/h) for that specific segment.
      3. If it STILL takes >100% at eco-speed, mark as physically unreachable.
      4. Calculate time correctly using Distance / Velocity (or TomTom real-world time).

    Returns:
        (energy_mat, time_mat, road_km_mat) — road_km_mat contains actual km for
        each edge (from cache or haversine fallback), used by visualization.
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

            # ATTEMPT 1: Target Velocity
            vel = target_velocity_kmh
            mult = (vel / base_velocity_kmh) ** 1.6
            base_kwh = (dist_km / 100.0) * consumption_kwh_per_100km
            
            kwh_req = base_kwh * mult
            energy_pct = (kwh_req / battery_capacity_kwh) * 100.0
            
            # ATTEMPT 2: Dynamic Eco-Fallback if it's too aggressive
            if energy_pct > 99.0 and vel > base_velocity_kmh:
                vel = base_velocity_kmh
                mult = 1.0
                kwh_req = base_kwh * mult
                energy_pct = (kwh_req / battery_capacity_kwh) * 100.0
                
            if energy_pct > 99.0:
                energy_mat[i, j] = 1000.0
                time_mat[i, j] = 10000.0
                continue
                
            # Populate Matrices
            energy_mat[i, j] = energy_pct
            
            # If we received a real-world time and target velocity is eco-speed, trust the API time.
            # Otherwise use physics logic to represent speeding up.
            if base_time_min is not None and vel <= base_velocity_kmh:
                time_mat[i, j] = base_time_min
            else:
                time_mat[i, j] = (dist_km / vel) * 60.0

    if coords is not None:
        total_edges = n * (n - 1)
        fallback_count = total_edges - cache_hits - api_hits
        print(f"       -> Road data: {cache_hits}/{total_edges} from DB cache, "
              f"{api_hits} live API, {fallback_count} haversine fallback")

    return energy_mat, time_mat, road_km_mat
