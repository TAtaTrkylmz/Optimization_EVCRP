"""
NumPy matrix computations: haversine, energy, travel time.
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


def energy_matrix(
    dist_mat: np.ndarray,
    road_factor: float,
    consumption_kwh_per_100km: float,
    battery_capacity_kwh: float,
) -> np.ndarray:
    """Energy cost (% of battery) for each node pair.

    NOTE: external factors (weather, terrain) will be per-region CSV multipliers
    in the future.  For now this is the nominal consumption.
    """
    road_km = dist_mat * road_factor
    kwh = (road_km / 100.0) * consumption_kwh_per_100km
    return (kwh / battery_capacity_kwh) * 100.0


def time_matrix(
    dist_mat: np.ndarray,
    crow_total_km: float,
    drive_total_min: float,
) -> np.ndarray:
    """Travel time (min) for each node pair, scaled from TomTom total."""
    if crow_total_km < 1e-3:
        return np.zeros_like(dist_mat)
    return dist_mat * (drive_total_min / crow_total_km)
