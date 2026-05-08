"""
Evolutionary Algorithm solver for the EV charging route problem.

Chromosome = list of (station_node_index, charge_pct) pairs.
Fitness = Z-score (lower is better).
"""
from __future__ import annotations

import random

import numpy as np

from planner.setup.config import (
    ANXIETY_THRESHOLD, B_MAX, ENERGY_COST_PER_PCT, CHARGE_STEP_PCT,
    DC_EFFICIENCY, EA_CROSSOVER_RATE, EA_GENERATIONS, EA_MUTATION_RATE,
    EA_POP_SIZE, EA_TOURNAMENT_K, UserPreferences,
)
from planner.setup.models import ChargingStop, RouteResult
from api.mocker import get_mock_station_occupancy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def charge_time_min(charge_pct: float, max_kw: float, cap_kwh: float) -> float:
    """Time (min) to add `charge_pct` % on a charger rated `max_kw`."""
    if charge_pct <= 0 or max_kw <= 0:
        return 0.0
    kw_eff = max(max_kw * DC_EFFICIENCY, 1.0)
    kwh = (charge_pct / 100.0) * cap_kwh
    return (kwh / kw_eff) * 60.0


# ---------------------------------------------------------------------------
# Plan evaluation
# ---------------------------------------------------------------------------

def evaluate_plan(
    stops: list[tuple[int, float]],
    n: int,
    energy_mat: np.ndarray,
    time_mat: np.ndarray,
    station_kw: np.ndarray,
    station_meta: list[tuple[str, str]],
    prefs: UserPreferences,
) -> tuple[float, dict | None]:
    """Simulate a charging plan and compute the Z-score.

    Returns (z_score, details_dict) or (inf, None) if infeasible.
    """
    INF = float("inf")
    b_floor = prefs.battery_min_enroute_pct
    b_ceil = prefs.battery_max_enroute_pct
    cap = prefs.battery_capacity_kwh

    # Build sorted path with origin/dest
    charge_map: dict[int, float] = {}
    for idx, q in stops:
        if 0 < idx < n - 1 and q > 0:
            charge_map[idx] = charge_map.get(idx, 0) + q

    path = sorted(set([0] + list(charge_map.keys()) + [n - 1]))

    battery = prefs.battery_start_pct
    total_drive = 0.0
    total_ct = 0.0
    total_wt = 0.0
    total_energy_spent = 0.0           # total energy consumed
    total_anx = 0.0
    current_time_min = 0.0

    for step in range(len(path) - 1):
        i, j = path[step], path[step + 1]

        q = charge_map.get(i, 0.0)
        if q > 0:
            if battery + q > b_ceil + 0.01:
                return INF, None
            battery = min(battery + q, b_ceil)
            
            sid = station_meta[i - 1][0]
            wt = get_mock_station_occupancy(sid, current_time_min)["wait_time_min"]
            ct = charge_time_min(q, float(station_kw[i]), cap)
            
            total_wt += wt
            total_ct += ct
            current_time_min += wt + ct

        e = energy_mat[i, j]
        battery -= e
        total_energy_spent += e          # accumulate energy spent on this segment
        if battery < b_floor - 0.01:
            return INF, None

        total_anx += max(0.0, ANXIETY_THRESHOLD - battery)
        
        drive_t = time_mat[i, j]
        total_drive += drive_t
        current_time_min += drive_t

    if battery < prefs.battery_end_min_pct - 0.01:
        return INF, None

    total_cc = total_energy_spent * ENERGY_COST_PER_PCT

    z = (prefs.w_time * (total_drive + total_ct + total_wt)
         + prefs.w_cost * total_cc
         + prefs.w_anxiety * total_anx)

    return z, {
        "path": path,
        "charge_map": charge_map,
        "total_drive": total_drive,
        "total_ct": total_ct,
        "total_wt": total_wt,
        "total_cc": total_cc,
        "total_energy_spent": total_energy_spent,
        "battery_dest": battery,
        "z": z,
    }


# ---------------------------------------------------------------------------
# Result builder
# ---------------------------------------------------------------------------

def build_result(
    rank: int,
    path: list[int],
    charges: dict[int, float],
    energy_mat: np.ndarray,
    time_mat: np.ndarray,
    station_kw: np.ndarray,
    station_meta: list[tuple[str, str]],
    coords: list[tuple[float, float]],
    prefs: UserPreferences,
) -> RouteResult:
    """Convert a path + charge map into a full RouteResult."""
    n = len(coords)
    stops: list[ChargingStop] = []
    total_drive = total_ct = total_wt = 0.0
    total_energy_spent = 0.0           # total energy consumed driving (for cost)
    battery = prefs.battery_start_pct
    cap = prefs.battery_capacity_kwh
    current_time_min = 0.0

    for step in range(len(path) - 1):
        i, j = path[step], path[step + 1]
        q = charges.get(i, 0)
        if 0 < i < n and q > 0:
            kw = float(station_kw[i])
            sid, sname = station_meta[i - 1]
            
            wt = get_mock_station_occupancy(sid, current_time_min)["wait_time_min"]
            ct = charge_time_min(q, kw, cap)
            cc = q * ENERGY_COST_PER_PCT
            
            stops.append(ChargingStop(
                node_index=i, station_id=sid,
                station_name=sname[:60] if sname else f"Station {sid}",
                lat=coords[i][0], lon=coords[i][1], max_kw=kw,
                battery_on_arrival_pct=round(battery, 1),
                charge_amount_pct=round(q, 1),
                battery_on_departure_pct=round(battery + q, 1),
                charge_time_min=round(ct, 1), charge_cost=round(cc, 1),
                wait_time_min=round(wt, 1),
                arrival_time_min=round(current_time_min, 1),
                departure_time_min=round(current_time_min + wt + ct, 1)
            ))
            total_wt += wt
            total_ct += ct
            current_time_min += wt + ct
            battery += q
            
        e = energy_mat[i, j]
        battery -= e
        total_energy_spent += e          # accumulate energy spent
        drive_t = time_mat[i, j]
        total_drive += drive_t
        current_time_min += drive_t

    # TODO: add POI-based suggestions once POI CSV is available.
    # See _generate_suggestions (commented out) for the logic skeleton.

    # Cost = total energy consumed driving × rate per %
    total_cc = total_energy_spent * ENERGY_COST_PER_PCT

    z = (prefs.w_time * (total_drive + total_ct + total_wt)
         + prefs.w_cost * total_cc
         + prefs.w_anxiety * sum(
             max(0, ANXIETY_THRESHOLD - s.battery_on_arrival_pct) for s in stops))

    return RouteResult(
        rank=rank,
        path_node_indices=path,
        stops=stops,
        total_drive_time_min=round(total_drive, 1),
        total_charge_time_min=round(total_ct, 1),
        total_wait_time_min=round(total_wt, 1),
        total_time_min=round(total_drive + total_ct + total_wt, 1),
        total_cost=round(total_cc, 1),
        z_score=round(z, 2),
        battery_at_destination_pct=round(max(0, battery), 1),
    )


# ---------------------------------------------------------------------------
# Greedy baseline
# ---------------------------------------------------------------------------

def greedy_baseline(
    n: int,
    energy_mat: np.ndarray,
    prefs: UserPreferences,
) -> list[tuple[int, float]]:
    """Base case: charge to ceiling at the farthest reachable station, repeat."""
    battery = prefs.battery_start_pct
    b_ceil = prefs.battery_max_enroute_pct
    b_floor = prefs.battery_min_enroute_pct
    stops: list[tuple[int, float]] = []
    current = 0

    while current < n - 1:
        farthest = current
        for j in range(current + 1, n):
            if battery - energy_mat[current, j] >= b_floor:
                farthest = j
            else:
                break

        if farthest == n - 1:
            break

        if farthest <= current:
            farthest = min(current + 1, n - 1)
            battery -= energy_mat[current, farthest]
            charge = max(0.0, b_ceil - battery)
            battery = min(battery + charge, b_ceil)
            if charge > 0 and farthest < n - 1:
                stops.append((farthest, round(charge)))
            current = farthest
            continue

        battery -= energy_mat[current, farthest]
        charge = max(0.0, b_ceil - battery)
        battery = min(battery + charge, b_ceil)
        if charge > 0:
            stops.append((farthest, round(charge)))
        current = farthest

    return stops


# ---------------------------------------------------------------------------
# GA operators
# ---------------------------------------------------------------------------

def _generate_initial_population(
    n: int,
    energy_mat: np.ndarray,
    prefs: UserPreferences,
    pop_size: int,
) -> list[list[tuple[int, float]]]:
    """Diverse initial population: greedy + partial ceilings + random."""
    rng = random.Random(42)
    population: list[list[tuple[int, float]]] = []

    population.append(greedy_baseline(n, energy_mat, prefs))

    # Partial-ceiling variants
    orig_ceil = prefs.battery_max_enroute_pct
    for partial in [80.0, 70.0, 60.0, 50.0]:
        prefs.battery_max_enroute_pct = min(partial, orig_ceil)
        population.append(greedy_baseline(n, energy_mat, prefs))
    prefs.battery_max_enroute_pct = orig_ceil

    # Stride patterns
    all_stations = list(range(1, n - 1))
    for step in [2, 3, 4]:
        stops = [(idx, float(rng.choice([30, 40, 50, 60, 70, 80])))
                 for idx in all_stations[::step]]
        population.append(stops)

    # Random subsets
    while len(population) < pop_size:
        k = rng.randint(1, max(1, len(all_stations) // 2))
        chosen = sorted(rng.sample(all_stations, min(k, len(all_stations))))
        stops = [(idx, float(min(rng.choice([20, 30, 40, 50, 60, 70, 80, 90, 100]),
                                  prefs.battery_max_enroute_pct)))
                 for idx in chosen]
        population.append(stops)

    return population[:pop_size]


def _mutate(
    stops: list[tuple[int, float]],
    n: int,
    b_ceil: float,
    rng: random.Random,
) -> list[tuple[int, float]]:
    """Random mutation: add/remove/tweak/swap/split."""
    stops = list(stops)
    all_stations = list(range(1, n - 1))
    if not all_stations:
        return stops

    op = rng.choice(["add", "remove", "tweak", "swap", "split"])

    if op == "add" or not stops:
        stops.append((rng.choice(all_stations),
                       float(min(rng.choice([30, 50, 70, 90]), b_ceil))))

    elif op == "remove" and len(stops) > 1:
        stops.pop(rng.randrange(len(stops)))

    elif op == "tweak" and stops:
        i = rng.randrange(len(stops))
        idx, q = stops[i]
        stops[i] = (idx, float(max(5, min(b_ceil, q + rng.choice([-20, -10, -5, 5, 10, 20])))))

    elif op == "swap" and stops:
        i = rng.randrange(len(stops))
        stops[i] = (rng.choice(all_stations), stops[i][1])

    elif op == "split" and stops:
        i = rng.randrange(len(stops))
        idx, q = stops[i]
        if q >= 30:
            q1, q2 = round(q * 0.5), round(q * 0.5)
            neighbors = [s for s in all_stations if abs(s - idx) <= 3 and s != idx]
            if neighbors:
                stops[i] = (idx, float(q1))
                stops.append((rng.choice(neighbors), float(q2)))

    # Merge duplicates
    merged: dict[int, float] = {}
    for idx, q in stops:
        merged[idx] = merged.get(idx, 0) + q
    return [(idx, min(q, b_ceil)) for idx, q in sorted(merged.items())]


def _crossover(
    p1: list[tuple[int, float]],
    p2: list[tuple[int, float]],
    b_ceil: float,
    rng: random.Random,
) -> list[tuple[int, float]]:
    """Merge parents: union of stations, averaged charges."""
    combined: dict[int, list[float]] = {}
    for idx, q in p1:
        combined.setdefault(idx, []).append(q)
    for idx, q in p2:
        combined.setdefault(idx, []).append(q)

    child: list[tuple[int, float]] = []
    for idx in sorted(combined):
        if rng.random() < 0.6:
            avg = sum(combined[idx]) / len(combined[idx])
            avg = round(avg / CHARGE_STEP_PCT) * CHARGE_STEP_PCT
            avg = max(CHARGE_STEP_PCT, min(b_ceil, avg))
            child.append((idx, float(avg)))
    return child


# ---------------------------------------------------------------------------
# Main EA loop
# ---------------------------------------------------------------------------

def solve(
    n: int,
    energy_mat: np.ndarray,
    time_mat: np.ndarray,
    station_kw: np.ndarray,
    station_meta: list[tuple[str, str]],
    coords: list[tuple[float, float]],
    prefs: UserPreferences,
) -> tuple[RouteResult, list[dict], list[float]]:
    """Run the evolutionary algorithm.

    Returns:
        best_route:       the single best RouteResult
        all_evaluated:    all unique feasible solutions (sorted by Z-score)
        best_per_gen:     best Z-score at each generation (for plotting)
    """
    rng = random.Random(42)
    INF = float("inf")
    b_ceil = prefs.battery_max_enroute_pct

    population = _generate_initial_population(n, energy_mat, prefs, EA_POP_SIZE)

    seen: set[tuple] = set()
    all_evaluated: list[dict] = []
    best_per_gen: list[float] = []
    
    no_improve_count = 0
    global_best_z = INF

    def _key(stops):
        return tuple(sorted((idx, round(q)) for idx, q in stops))

    def _eval(stops):
        key = _key(stops)
        z, det = evaluate_plan(stops, n, energy_mat, time_mat, station_kw, station_meta, prefs)
        if key not in seen and z < INF:
            seen.add(key)
            all_evaluated.append({
                "z": z,
                "stops": list(stops),
                "n_stops": len([q for _, q in stops if q > 0]),
                "total_time": det["total_drive"] + det["total_ct"] + det["total_wt"],
                "cost": det["total_cc"],
                "dest_soc": det["battery_dest"],
                "path": det["path"],
                "charge_map": det["charge_map"],
            })
        return z

    fitnesses = [_eval(ind) for ind in population]

    for gen in range(EA_GENERATIONS):
        new_pop: list[list[tuple[int, float]]] = []

        # Elitism
        ranked = sorted(range(len(population)), key=lambda i: fitnesses[i])
        for i in ranked[:5]:
            new_pop.append(population[i])

        while len(new_pop) < EA_POP_SIZE:
            def _tournament():
                cands = rng.sample(range(len(population)),
                                   min(EA_TOURNAMENT_K, len(population)))
                return list(population[min(cands, key=lambda i: fitnesses[i])])

            if rng.random() < EA_CROSSOVER_RATE:
                child = _crossover(_tournament(), _tournament(), b_ceil, rng)
            else:
                child = _tournament()

            if rng.random() < EA_MUTATION_RATE:
                child = _mutate(child, n, b_ceil, rng)

            new_pop.append(child)

        population = new_pop
        fitnesses = [_eval(ind) for ind in population]

        best_z = min(fitnesses)
        best_per_gen.append(best_z if best_z < INF else float("nan"))
        
        # Early stopping tracking
        if best_z < global_best_z - 0.01:
            global_best_z = best_z
            no_improve_count = 0
        else:
            no_improve_count += 1

        if (gen + 1) % 20 == 0 or gen == 0 or no_improve_count >= 50 or gen == EA_GENERATIONS - 1:
            feas = sum(1 for f in fitnesses if f < INF)
            print(f"       gen {gen+1:>3}/{EA_GENERATIONS}: "
                  f"best Z={best_z:.1f}  feasible={feas}/{len(population)}  "
                  f"unique={len(all_evaluated)}")
                  
        # Break if no improvement for 50 generations
        if no_improve_count >= 50:
            print(f"       -> Early stopping at gen {gen+1} (no improvement for 50 gens)")
            break

    # Sort all evaluated solutions
    all_evaluated.sort(key=lambda d: d["z"])

    # Build best RouteResult if any exist
    best_route = None
    if all_evaluated:
        best = all_evaluated[0]
        best_route = build_result(
            1, best["path"], best["charge_map"],
            energy_mat, time_mat, station_kw, station_meta, coords, prefs,
        )

    return best_route, all_evaluated, best_per_gen


# ---------------------------------------------------------------------------
# POI suggestions (commented out — waiting for real POI data)
# ---------------------------------------------------------------------------

# def generate_suggestions(stops: list[ChargingStop], poi_df) -> list[dict]:
#     """Generate contextual suggestions based on nearby POIs.
#
#     Will load POI data from a CSV with real coordinates.
#     For each charging stop, find nearby POIs and suggest activities
#     based on charging duration:
#       < 5 min  -> "Quick top-up, no need to leave the car"
#       < 20 min -> "Grab a snack at ..."
#       >= 20 min -> "Great time for a meal at ... or coffee at ..."
#     """
#     suggestions = []
#     for stop in stops:
#         ct = stop.charge_time_min
#         nearby = find_pois_near(stop.lat, stop.lon, poi_df, radius_m=500)
#         if ct < 5:
#             suggestions.append({
#                 "station": stop.station_name,
#                 "message": f"Quick top-up ({ct:.0f} min). No need to leave the car.",
#             })
#         elif ct < 20:
#             suggestions.append({
#                 "station": stop.station_name,
#                 "message": f"Moderate charge ({ct:.0f} min). Visit {nearby[0]['name']}.",
#                 "pois": nearby[:2],
#             })
#         else:
#             suggestions.append({
#                 "station": stop.station_name,
#                 "message": f"Extended charge ({ct:.0f} min). Meal at {nearby[0]['name']}.",
#                 "pois": nearby[:4],
#             })
#     return suggestions
