"""
EVRoutePlanner — thin orchestrator that wires the pipeline together.
"""
from __future__ import annotations

import numpy as np

from planner.config import UserPreferences
from planner.models import RouteResult
from planner.tomtom import load_api_key, geocode, route_summary
from planner.stations import load_stations, filter_corridor, build_node_list
from planner.matrices import haversine_matrix, energy_matrix, time_matrix
from planner import ea_solver


class EVRoutePlanner:
    """EV route planner with evolutionary algorithm optimizer."""

    def __init__(self, prefs: UserPreferences):
        self.prefs = prefs
        # Filled after plan_route() for visualization
        self.coords: list[tuple[float, float]] = []
        self.station_meta: list[tuple[str, str]] = []
        self.dist_mat: np.ndarray | None = None
        self.road_factor: float = 1.0

    def plan_route(self) -> tuple[RouteResult, list[dict], list[float]]:
        """Run the full planning pipeline.

        Returns:
            best_route:     the single best RouteResult
            all_evaluated:  all feasible solutions ranked by Z-score
            convergence:    best Z per generation (for plotting)
        """
        api_key = load_api_key()

        print(f"[1/6] Geocoding source: {self.prefs.source!r}")
        lat_o, lon_o = geocode(self.prefs.source, api_key)
        print(f"       -> ({lat_o:.5f}, {lon_o:.5f})")

        print(f"[2/6] Geocoding destination: {self.prefs.destination!r}")
        lat_d, lon_d = geocode(self.prefs.destination, api_key)
        print(f"       -> ({lat_d:.5f}, {lon_d:.5f})")

        print("[3/6] Fetching driving route from TomTom...")
        road_km, drive_min = route_summary(lat_o, lon_o, lat_d, lon_d, api_key)
        print(f"       -> {road_km:.1f} km, {drive_min:.1f} min")

        print("[4/6] Loading & filtering charging stations...")
        stations = load_stations()
        corridor_df = filter_corridor(stations, lat_o, lon_o, lat_d, lon_d)
        print(f"       -> {len(corridor_df)} stations in corridor")
        if corridor_df.empty:
            print("WARNING: No charging stations found along the corridor!")
            raise RuntimeError("No stations in corridor.")

        print("[5/6] Building distance / energy / time matrices...")
        coords, station_kw, station_meta = build_node_list(
            lat_o, lon_o, lat_d, lon_d, corridor_df,
        )
        n = len(coords)
        coords_np = np.array(coords)
        dist_mat = haversine_matrix(coords_np)
        crow_total = float(dist_mat[0, n - 1])
        rf = road_km / max(crow_total, 1e-3)
        e_mat = energy_matrix(dist_mat, rf,
                              self.prefs.consumption_kwh_per_100km,
                              self.prefs.battery_capacity_kwh)
        t_mat = time_matrix(dist_mat, crow_total, drive_min)
        print(f"       -> {n} nodes, matrices {dist_mat.shape}")

        print("[6/6] Running evolutionary optimisation...")
        kw_arr = np.array([0.0] + station_kw + [0.0])
        best_route, all_evaluated, convergence = ea_solver.solve(
            n, e_mat, t_mat, kw_arr, station_meta, coords, self.prefs,
        )

        # Print Z-score table
        print(f"\n{'-'*64}")
        print(f"  Z-SCORE TABLE  ({len(all_evaluated)} feasible solutions)")
        print(f"{'-'*64}")
        print(f"  {'#':<5} {'Z-score':<12} {'Stops':<7} "
              f"{'Time(min)':<11} {'Cost(TL)':<10} {'Dest SOC'}")
        print(f"  {'-'*5} {'-'*11} {'-'*6} {'-'*10} {'-'*9} {'-'*8}")
        for idx, e in enumerate(all_evaluated[:30], 1):
            print(f"  {idx:<5} {e['z']:<12.2f} {e['n_stops']:<7} "
                  f"{e['total_time']:<11.1f} {e['cost']:<10.1f} "
                  f"{e['dest_soc']:.1f}%")
        if len(all_evaluated) > 30:
            print(f"  ... ({len(all_evaluated) - 30} more omitted)")
        print(f"{'-'*64}\n")

        # Store for visualization
        self.coords = coords
        self.station_meta = station_meta
        self.dist_mat = dist_mat
        self.road_factor = rf

        return best_route, all_evaluated, convergence
