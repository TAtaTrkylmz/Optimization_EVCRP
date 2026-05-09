"""
pipeline — Multi-leg route planning orchestrator.

Data flow:
    1. Geocode all waypoints (source + destinations)
    2. For each consecutive pair (leg), run the single-leg planner:
       a. Get TomTom route summary -> road_km, drive_min
       b. Filter corridor charging stations
       c. Build distance / energy / time matrices
       d. Run EA solver
    3. Chain battery SOC between legs (end of leg N = start of leg N+1)
    4. (Future) ALNS improvement over SOC handoffs
    5. Aggregate into MultiLegResult

Usage:
    from planner.pipeline import plan_journey
    result = plan_journey(prefs)
"""
from __future__ import annotations

import numpy as np

from planner.setup.config import (
    UserPreferences, BASE_VELOCITY_KMH, CRUISE_VELOCITY_KMH,
    ANXIETY_RANGE_KM,
)
from planner.setup.models import LegResult, MultiLegResult
from planner.setup.tomtom import load_api_key, geocode, route_summary, route_with_geometry
from planner.setup.stations import load_stations, filter_corridor, build_node_list
from planner.setup.matrices import haversine_matrix, build_cost_matrices
from planner.setup import ea_solver
from planner.setup.logger import log
from api.mocker import get_mock_weather, WeatherSquare


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _geocode_location(name: str, api_key: str) -> tuple[float, float]:
    """Geocode a single location and print the result."""
    lat, lon = geocode(name, api_key)
    log.step(f"{name} -> ({lat:.5f}, {lon:.5f})")
    return lat, lon


def _get_route_info(lat_o, lon_o, lat_d, lon_d, api_key):
    """Fetch TomTom route summary between two coordinates."""
    road_km, drive_min = route_summary(lat_o, lon_o, lat_d, lon_d, api_key)
    log.step(f"{road_km:.1f} km, {drive_min:.1f} min")
    return road_km, drive_min


def _filter_stations(stations, lat_o, lon_o, lat_d, lon_d):
    """Filter corridor stations for a single leg."""
    corridor_df = filter_corridor(stations, lat_o, lon_o, lat_d, lon_d)
    log.step(f"{len(corridor_df)} stations in corridor")
    if corridor_df.empty:
        raise RuntimeError("No charging stations found along the corridor!")
    return corridor_df


def _build_matrices(lat_o, lon_o, lat_d, lon_d, corridor_df, prefs):
    """Build node list and distance/energy/time matrices for a leg."""
    coords, station_kw, station_meta = build_node_list(
        lat_o, lon_o, lat_d, lon_d, corridor_df,
    )
    n = len(coords)
    coords_np = np.array(coords)
    dist_mat = haversine_matrix(coords_np)

    # Road factor: ratio of real road km to straight-line km
    crow_total = float(dist_mat[0, n - 1])

    return coords, station_kw, station_meta, n, dist_mat, crow_total


def _print_zscore_table(all_evaluated):
    """Print top 30 solutions from the EA Z-score table."""
    log.info(f"")
    log.info(f"{'-'*72}")
    log.info(f"  Z-SCORE TABLE  ({len(all_evaluated)} feasible solutions)")
    log.info(f"{'-'*72}")
    log.info(f"  {'#':<5} {'Z-score':<12} {'Stops':<7} "
             f"{'Time(min)':<11} {'Cost(TL)':<10} {'Dist(km)':<10} {'Dest SOC'}")
    log.info(f"  {'-'*5} {'-'*11} {'-'*6} {'-'*10} {'-'*9} {'-'*9} {'-'*8}")
    for idx, e in enumerate(all_evaluated[:30], 1):
        log.info(f"  {idx:<5} {e['z']:<12.2f} {e['n_stops']:<7} "
                 f"{e['total_time']:<11.1f} {e['cost']:<10.1f} "
                 f"{e.get('distance', 0):<10.1f} {e['dest_soc']:.1f}%")
    if len(all_evaluated) > 30:
        log.info(f"  ... ({len(all_evaluated) - 30} more omitted)")
    log.info(f"{'-'*72}")

# ---------------------------------------------------------------------------
# Partial route builder (for infeasible cases)
# ---------------------------------------------------------------------------

def _build_partial_route(
    n: int,
    energy_mat: np.ndarray,
    prefs: UserPreferences,
) -> tuple[list[int], float]:
    """Build a partial route showing how far the vehicle can get.

    Greedy hop-by-hop: from origin, visit consecutive stations,
    charging to ceiling at each, until we can't reach the next one.

    Returns:
        (path_node_indices, battery_at_last_node)
    """
    battery = prefs.battery_start_pct
    b_ceil = prefs.battery_max_enroute_pct
    b_floor = prefs.battery_min_enroute_pct
    path = [0]
    current = 0

    for j in range(1, n):
        e = energy_mat[current, j]
        if e > 900:   # unreachable edge
            break
        if battery - e < b_floor:
            break
        battery -= e
        path.append(j)

        # Charge at every station we visit (not at destination)
        if j < n - 1:
            charge = max(0.0, b_ceil - battery)
            battery = min(battery + charge, b_ceil)

        current = j

    return path, round(battery, 1)


# ---------------------------------------------------------------------------
# Single-leg planner
# ---------------------------------------------------------------------------

def plan_single_leg(
    origin_name: str,
    dest_name: str,
    lat_o: float, lon_o: float,
    lat_d: float, lon_d: float,
    battery_start_pct: float,
    prefs: UserPreferences,
    stations,
    api_key: str,
    leg_index: int = 0,
    live_traffic: bool = False,
    weather_squares: list[WeatherSquare] | None = None,
) -> LegResult:
    """Plan a single leg from origin to destination.

    Args:
        origin_name:      human-readable origin
        dest_name:        human-readable destination
        lat_o, lon_o:     origin coordinates
        lat_d, lon_d:     destination coordinates
        battery_start_pct: battery SOC at start of this leg
        prefs:            user preferences (velocity, weights, etc.)
        stations:         pre-loaded station DataFrame
        api_key:          TomTom API key
        leg_index:        0-based leg number
        live_traffic:     whether to check live traffic instead of historical cache

    Returns:
        LegResult with route, convergence, and visualization data.
    """
    prefix = f"[Leg {leg_index + 1}]"

    # 1. TomTom route summary
    with log.timed(f"{prefix} Fetching route: {origin_name} -> {dest_name}"):
        road_km, drive_min = route_summary(lat_o, lon_o, lat_d, lon_d, api_key, use_cache=True, live_traffic=live_traffic)
        log.step(f"{road_km:.1f} km, {drive_min:.1f} min")

    # 2. Filter corridor stations
    with log.timed(f"{prefix} Filtering corridor stations"):
        corridor_df = _filter_stations(stations, lat_o, lon_o, lat_d, lon_d)

    # 3. Build matrices
    with log.timed(f"{prefix} Building cost matrices (with road cache)"):
        coords, station_kw, station_meta, n, dist_mat, crow_total = \
            _build_matrices(lat_o, lon_o, lat_d, lon_d, corridor_df, prefs)

        rf = road_km / max(crow_total, 1e-3)

        # 3b. Build Cost Matrices using Dynamic Eco-Routing Fallback
        e_mat, t_mat, road_km_mat = build_cost_matrices(
            dist_mat, rf,
            prefs.consumption_kwh_per_100km,
            prefs.battery_capacity_kwh,
            target_velocity_kmh=prefs.velocity_kmh,
            coords=coords,
            api_key=api_key,
            live_traffic=live_traffic,
            weather_squares=weather_squares,
        )
        weather_info = ""
        if weather_squares:
            weather_info = f", {len(weather_squares)} weather zones active"
        log.step(f"{n} nodes, energy@{BASE_VELOCITY_KMH:.0f}km/h  "
                 f"time@{CRUISE_VELOCITY_KMH:.0f}km/h{weather_info}")

    # 4. Create a temporary prefs copy with this leg's battery_start
    is_final_leg = (leg_index == len(prefs.destinations) - 1)
    leg_prefs = _make_leg_prefs(prefs, battery_start_pct, is_final_leg)

    # Log the computed anxiety threshold
    log.metric("Anxiety threshold", f"{leg_prefs.anxiety_threshold:.1f}% "
               f"(range={prefs.range_km:.0f}km, ceil={prefs.battery_max_enroute_pct:.0f}%, "
               f"w-range={ANXIETY_RANGE_KM:.0f}km)")

    # 5. Run EA solver
    with log.timed(f"{prefix} Running EA optimisation"):
        kw_arr = np.array([0.0] + station_kw + [0.0])
        best_route, all_evaluated, convergence = ea_solver.solve(
            n, e_mat, t_mat, kw_arr, station_meta, coords, leg_prefs,
            road_km_mat,
        )

    if not all_evaluated:
        # Build a partial route showing how far we can get
        log.warn(f"{prefix} No feasible route found! Building partial route...")
        partial_path, partial_battery = _build_partial_route(
            n, e_mat, leg_prefs
        )
        last_node = partial_path[-1] if partial_path else 0
        last_coord = coords[last_node]
        log.warn(f"Vehicle stranded at node {last_node} "
                 f"({last_coord[0]:.4f}, {last_coord[1]:.4f}) "
                 f"with {partial_battery:.1f}% battery")
        
        # Build a minimal RouteResult for the partial path
        from planner.setup.models import RouteResult
        partial_route = RouteResult(
            rank=0,
            path_node_indices=partial_path,
            stops=[],
            total_drive_time_min=0.0,
            total_charge_time_min=0.0,
            total_wait_time_min=0.0,
            total_time_min=0.0,
            total_cost=0.0,
            total_distance_km=0.0,
            z_score=float('inf'),
            battery_at_destination_pct=partial_battery,
            is_partial=True,
        )
        
        # Fetch geometry for partial path
        route_geometries = {}
        for step in range(len(partial_path) - 1):
            ni, nj = partial_path[step], partial_path[step + 1]
            lat1, lon1 = coords[ni]
            lat2, lon2 = coords[nj]
            geo = route_with_geometry(lat1, lon1, lat2, lon2, api_key)
            route_geometries[(ni, nj)] = geo
        
        return LegResult(
            leg_index=leg_index,
            origin=origin_name,
            destination=dest_name,
            route=partial_route,
            convergence=convergence,
            feasible_routes_found=0,
            coords=coords,
            station_meta=station_meta,
            dist_mat=dist_mat,
            road_km_mat=road_km_mat,
            road_factor=rf,
            route_geometries=route_geometries,
        )

    # Z-score table
    _print_zscore_table(all_evaluated)

    # 6. Fetch road geometry for the traveled edges (only 2-5 API calls)
    with log.timed(f"{prefix} Fetching road geometry for traveled path"):
        path = best_route.path_node_indices
        route_geometries: dict[tuple[int,int], list[tuple[float,float]]] = {}
        for step in range(len(path) - 1):
            ni, nj = path[step], path[step + 1]
            lat1, lon1 = coords[ni]
            lat2, lon2 = coords[nj]
            geo = route_with_geometry(lat1, lon1, lat2, lon2, api_key)
            route_geometries[(ni, nj)] = geo
        log.step(f"{len(route_geometries)} road segments fetched")
        
    return LegResult(
        leg_index=leg_index,
        origin=origin_name,
        destination=dest_name,
        route=best_route,
        convergence=convergence,
        feasible_routes_found=len(all_evaluated),
        coords=coords,
        station_meta=station_meta,
        dist_mat=dist_mat,
        road_km_mat=road_km_mat,
        road_factor=rf,
        route_geometries=route_geometries,
    )


def _make_leg_prefs(prefs: UserPreferences, battery_start: float, is_final_leg: bool) -> UserPreferences:
    """Create a copy of prefs with adjusted battery_start for a specific leg."""
    
    # For intermediate legs, require arriving with at least 50% (or the user's end min)
    # so we don't start the next leg stranded. (ALNS will optimize this later)
    end_pct = prefs.battery_end_min_pct if is_final_leg else max(prefs.battery_end_min_pct, 50.0)
    
    return UserPreferences(
        source=prefs.source,
        destinations=prefs.destinations,
        battery_start_pct=battery_start,
        battery_end_min_pct=end_pct,
        battery_capacity_kwh=prefs.battery_capacity_kwh,
        consumption_kwh_per_100km=prefs.consumption_kwh_per_100km,
        range_km=prefs.range_km,
        priority_time=prefs.priority_time,
        priority_cost=prefs.priority_cost,
        priority_anxiety=prefs.priority_anxiety,
        battery_min_enroute_pct=prefs.battery_min_enroute_pct,
        battery_max_enroute_pct=prefs.battery_max_enroute_pct,
    )


# ---------------------------------------------------------------------------
# Multi-leg planner
# ---------------------------------------------------------------------------

def plan_journey(prefs: UserPreferences, live_traffic: bool = False,
                 weather_seed: int = 42) -> MultiLegResult:
    """Plan the full multi-leg journey.

    Steps:
        1. Geocode all waypoints
        2. Load stations once (shared across all legs)
        2b. Generate mock weather over Turkey
        3. Plan each leg sequentially, chaining battery SOC
        4. (Future) ALNS improvement
        5. Return aggregated MultiLegResult
    """
    log.mark_journey_start()
    api_key = load_api_key()

    # Build the full waypoint list: [source, dest1, dest2, ..., final_dest]
    waypoints = [prefs.source] + list(prefs.destinations)
    n_legs = len(waypoints) - 1

    log.section(f"EV ROUTE PLANNER - {n_legs} leg(s)")
    log.info(f"  Itinerary: {' -> '.join(waypoints)}")
    log.info(f"  Battery   : {prefs.battery_start_pct:.0f}% start"
             f" -> {prefs.battery_end_min_pct:.0f}% min at final dest")
    log.info(f"  Enroute   : floor={prefs.battery_min_enroute_pct:.0f}%"
             f"  ceil={prefs.battery_max_enroute_pct:.0f}%")
    log.info(f"  Vehicle   : {prefs.battery_capacity_kwh} kWh,"
             f" {prefs.consumption_kwh_per_100km} kWh/100km,"
             f" range={prefs.range_km:.0f}km")
    log.info(f"  Velocity  : energy@{BASE_VELOCITY_KMH:.0f}km/h (eco)"
             f"  time@{CRUISE_VELOCITY_KMH:.0f}km/h (cruise)")
    log.info(f"  Priorities: time={prefs.priority_time}"
             f"  cost={prefs.priority_cost}"
             f"  anxiety={prefs.priority_anxiety}")
    log.info(f"  Weights   : time={prefs.w_time:.1f}"
             f"  cost={prefs.w_cost:.1f}"
             f"  anxiety={prefs.w_anxiety:.1f}")
    log.info(f"  Anxiety   : threshold={prefs.anxiety_threshold:.1f}%"
             f"  (w-range={ANXIETY_RANGE_KM:.0f}km)")

    # Step 1: Geocode all waypoints
    with log.timed("Geocoding all waypoints"):
        wp_coords: list[tuple[float, float]] = []
        for i, wp in enumerate(waypoints):
            log.info(f"  [{i+1}/{len(waypoints)}] {wp}")
            wp_coords.append(_geocode_location(wp, api_key))

    # Step 2: Load stations once
    with log.timed("Loading charging station database"):
        stations = load_stations()
        log.step(f"{len(stations)} stations loaded")

    # Step 2b: Generate mock weather over Turkey
    weather_squares = get_mock_weather(seed=weather_seed)
    log.info(f"")
    log.info(f"Weather simulation (seed={weather_seed}): {len(weather_squares)} zones generated")
    for sq in weather_squares:
        log.step(str(sq))

    # Step 3: Plan each leg, chain battery SOC
    log.info(f"")
    log.info(f"Planning {n_legs} leg(s)...")
    legs: list[LegResult] = []
    battery = prefs.battery_start_pct

    for i in range(n_legs):
        src_name = waypoints[i]
        dst_name = waypoints[i + 1]
        lat_o, lon_o = wp_coords[i]
        lat_d, lon_d = wp_coords[i + 1]

        log.info(f"")
        log.info(f"{'-'*50}")
        log.info(f"  LEG {i+1}/{n_legs}: {src_name} -> {dst_name}")
        log.info(f"  Starting battery: {battery:.1f}%")
        log.info(f"{'-'*50}")

        # Simulate charging at the waypoint if battery is low
        if i > 0 and battery < 80.0:
            log.info(f"  (Simulating charge at {src_name} to 80.0% before departure)")
            battery = 80.0

        leg = plan_single_leg(
            origin_name=src_name,
            dest_name=dst_name,
            lat_o=lat_o, lon_o=lon_o,
            lat_d=lat_d, lon_d=lon_d,
            battery_start_pct=battery,
            prefs=prefs,
            stations=stations,
            api_key=api_key,
            leg_index=i,
            live_traffic=live_traffic,
            weather_squares=weather_squares,
        )
        legs.append(leg)

        # Chain battery: end of this leg = start of next
        battery = leg.route.battery_at_destination_pct
        log.info(f"  Battery at {dst_name}: {battery:.1f}%")
        log.metric("Distance", f"{leg.route.total_distance_km:.1f} km")

        # Warn if battery is low going into next leg
        if i < n_legs - 1 and battery < prefs.battery_min_enroute_pct + 5:
            log.warn(f"Low battery handoff ({battery:.1f}%) entering next leg!")

    # Step 4: ALNS improvement (future)
    legs = _alns_improve(legs, prefs)

    # Step 5: Aggregate
    result = MultiLegResult(legs=legs, weather_squares=weather_squares)
    _print_journey_summary(result)

    return result


# ---------------------------------------------------------------------------
# ALNS improvement (skeleton for future expansion)
# ---------------------------------------------------------------------------

def _alns_improve(legs: list[LegResult], prefs: UserPreferences) -> list[LegResult]:
    """ALNS-style improvement over multi-leg SOC handoffs.

    Adaptive Large Neighborhood Search structure:
      - Destroy: select a handoff point, adjust SOC target
      - Repair : re-plan affected legs with new battery constraints
      - Accept : keep if total Z-score improves

    Currently returns legs unchanged. The infrastructure is ready for
    when leg re-planning is optimised (cached corridors, faster EA).
    """
    if len(legs) < 2:
        return legs

    # Analyse current handoffs for logging
    log.info("")
    log.info("ALNS analysis (SOC handoffs):")
    for i in range(len(legs) - 1):
        soc = legs[i].route.battery_at_destination_pct
        next_leg = legs[i + 1]
        log.step(f"{legs[i].destination}: {soc:.1f}% "
                 f"-> Leg {i+2} starts with {soc:.1f}%")

    # TODO: implement destroy-repair iterations
    # for iteration in range(max_iterations):
    #     1. Pick a random handoff index
    #     2. Try adjusting battery_end_min for leg[i] by ±5, ±10
    #     3. Re-plan leg[i] and leg[i+1] with adjusted SOC
    #     4. Accept if total_z improves

    log.step("(Improvement iterations not yet active)")
    return legs


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------

def _print_journey_summary(result: MultiLegResult) -> None:
    """Print the aggregated journey summary."""
    log.section("JOURNEY SUMMARY")
    log.info(f"  Itinerary      : {result.itinerary}")
    log.info(f"  Total legs     : {len(result.legs)}")
    log.info(f"  Total distance : {result.total_distance_km:.1f} km")
    log.info(f"  Total drive    : {result.total_drive_time_min:.1f} min")
    log.info(f"  Total charge   : {result.total_charge_time_min:.1f} min")
    log.info(f"  Total time     : {result.total_time_min:.1f} min")
    log.info(f"  Total cost     : {result.total_cost:.1f} TL")
    log.info(f"  Total Z-score  : {result.total_z_score:.2f}")
    log.info(f"  Battery at end : {result.battery_at_final_dest:.1f}%")

    # Per-leg summary table
    log.info(f"")
    log.info(f"  {'Leg':<5} {'Route':<35} {'Dist(km)':<10} {'Time':<10} {'Cost':<10} {'Z':<10} {'End SOC'}")
    log.info(f"  {'-'*5} {'-'*35} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*8}")
    for leg in result.legs:
        route_str = f"{leg.origin} -> {leg.destination}"
        if len(route_str) > 35:
            route_str = route_str[:32] + "..."
        log.info(f"  {leg.leg_index+1:<5} {route_str:<35} "
                 f"{leg.route.total_distance_km:<10.1f} "
                 f"{leg.route.total_time_min:<10.1f} "
                 f"{leg.route.total_cost:<10.1f} "
                 f"{leg.route.z_score:<10.2f} "
                 f"{leg.route.battery_at_destination_pct:.1f}%")
    log.info(f"{'='*90}")
