"""
Charging station data: loading, corridor filtering, node list building.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from planner.config import DATA_CSV, MAX_CROSS_TRACK_KM, MAX_STATIONS_IN_MODEL


def load_stations() -> pd.DataFrame:
    """Load EPDK station CSV and aggregate by station number."""
    if not DATA_CSV.is_file():
        raise FileNotFoundError(f"Missing station data: {DATA_CSV}")
    df = pd.read_csv(DATA_CSV)
    df = df.dropna(subset=["Latitude", "Longitude"])
    return df.groupby("Station Id", as_index=False).agg({
        "Latitude": "first",
        "Longitude": "first",
        "Socket Power (kW)": "max",
        "Station Name": "first",
    })


def filter_corridor(
    stations: pd.DataFrame,
    lat_o: float, lon_o: float,
    lat_d: float, lon_d: float,
) -> pd.DataFrame:
    """Select stations within the corridor between origin and destination."""
    lats = stations["Latitude"].values.astype(float)
    lons = stations["Longitude"].values.astype(float)

    mean_lat_rad = np.radians((lat_o + lat_d + float(np.mean(lats))) / 3.0)
    sx = 6371.0 * np.cos(mean_lat_rad)
    sy = 6371.0

    x1 = sx * np.radians(lon_d - lon_o)
    y1 = sy * np.radians(lat_d - lat_o)
    path_len = np.hypot(x1, y1)
    if path_len < 1e-3:
        return pd.DataFrame()

    xp = sx * np.radians(lons - lon_o)
    yp = sy * np.radians(lats - lat_o)
    t = (xp * x1 + yp * y1) / (path_len ** 2)
    cross_km = np.hypot(xp - t * x1, yp - t * y1)

    mask = (cross_km <= MAX_CROSS_TRACK_KM) & (t >= -0.08) & (t <= 1.08)
    rows = []
    for idx in np.where(mask)[0]:
        r = stations.iloc[idx]
        kw = float(r["Socket Power (kW)"]) if pd.notna(r["Socket Power (kW)"]) else 22.0
        rows.append({
            "t": float(t[idx]),
            "cross_km": float(cross_km[idx]),
            "lat": float(r["Latitude"]),
            "lon": float(r["Longitude"]),
            "max_kw": kw,
            "id": r["Station Id"],
            "name": r["Station Name"] if pd.notna(r["Station Name"]) else "",
        })
    if not rows:
        return pd.DataFrame()

    out = pd.DataFrame(rows).sort_values("t").reset_index(drop=True)
    if len(out) <= MAX_STATIONS_IN_MODEL:
        return out

    # Sample evenly if too many stations
    nout = len(out)
    m = MAX_STATIONS_IN_MODEL
    indices = sorted({
        min(nout - 1, int(round(i * (nout - 1) / max(m - 1, 1))))
        for i in range(m)
    })
    return out.iloc[indices].reset_index(drop=True)


def build_node_list(
    lat_o: float, lon_o: float,
    lat_d: float, lon_d: float,
    corridor_df: pd.DataFrame,
) -> tuple[list[tuple[float, float]], list[float], list[tuple[str, str]]]:
    """Build ordered node list: [origin, stations..., destination].

    Returns:
        coords:       [(lat, lon), ...]
        station_kw:   [max_kw, ...]  (only for stations, not origin/dest)
        station_meta: [(id, name), ...]
    """
    coords = [(lat_o, lon_o)]
    station_kw: list[float] = []
    station_meta: list[tuple[str, str]] = []
    for _, r in corridor_df.iterrows():
        coords.append((float(r["lat"]), float(r["lon"])))
        station_kw.append(float(r["max_kw"]))
        station_meta.append((str(r["id"]), str(r["name"])))
    coords.append((lat_d, lon_d))
    return coords, station_kw, station_meta
