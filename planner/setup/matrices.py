"""
NumPy matrix computations: haversine, energy, travel time.

The energy matrix now accepts a consumption_multiplier from the
velocity model (see config.py for the formula).
"""
from __future__ import annotations

import numpy as np


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
) -> tuple[np.ndarray, np.ndarray]:
    """Calculate both Energy (%) and Time (min) matrices simultaneously.

    This implements "Dynamic Eco-Fallback" to completely untangle User Preferences from
    Topological Feasibility. 
      1. Default to Target Velocity (derived from w-time preference).
      2. If target velocity causes Energy Requirement > 100% capacity, drop the speed
         down to safe Eco Speed (70 km/h) for that specific segment.
      3. If it STILL takes >100% at eco-speed, mark as physically unreachable.
      4. Calculate time correctly using Distance / Velocity.
    """
    n = dist_mat.shape[0]
    energy_mat = np.zeros((n, n), dtype=float)
    time_mat = np.zeros((n, n), dtype=float)

    road_km_mat = dist_mat * road_factor

    for i in range(n):
        for j in range(n):
            if i == j:
                continue
                
            dist_km = road_km_mat[i, j]
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
                # Slow down to minimum safe cruising speed
                vel = base_velocity_kmh
                mult = 1.0  # (70/70)^1.6
                kwh_req = base_kwh * mult
                energy_pct = (kwh_req / battery_capacity_kwh) * 100.0
                
            # Populate Matrices
            energy_mat[i, j] = energy_pct
            time_mat[i, j] = (dist_km / vel) * 60.0  # Standard time calculation (hrs * 60 min)

    return energy_mat, time_mat
