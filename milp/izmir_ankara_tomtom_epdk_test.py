"""
End-to-end test: Izmir → Ankara using TomTom (geocode + route summary) and real EPDK
charging stations (geocoded_epdk_data.csv). Builds a forward corridor graph and solves the
same EV routing MILP structure as milp/MILP_solverfw_test.py.

Requires: TOMTOM_API_KEY in the environment or in a repo-root .env file (same as api/geocode_tomtom.py).

Run from repo root (repo has venv/; use it or activate first):
  ./venv/bin/python milp/izmir_ankara_tomtom_epdk_test.py
  ./venv/bin/python milp/izmir_ankara_tomtom_epdk_test.py -o output/my_run.txt

See doc/IZMIR_ANKARA_ROUTE_TEST.md for full documentation.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import pulp
import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_CSV = REPO_ROOT / "data" / "geocoded_epdk_data.csv"
DEFAULT_OUTPUT_TXT = REPO_ROOT / "output" / "izmir_ankara_last_run.txt"


class ReportLog:
    """Mirror lines to stdout and collect them for a .txt dump."""

    def __init__(self) -> None:
        self._lines: list[str] = []

    def line(self, text: str = "") -> None:
        self._lines.append(text)
        print(text)

    def write_file(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        body = "\n".join(self._lines) + "\n"
        path.write_text(body, encoding="utf-8")

TOMTOM_GEOCODE_BASE = "https://api.tomtom.com/search/2/geocode"

# Scenario
ORIGIN_QUERY = "Izmir, Turkey"
DEST_QUERY = "Ankara, Turkey"

# Vehicle / MILP (aligned with MILP_solverfw_test.py style)
B_MAX = 100.0
B_START = 100.0
THRESHOLD = 30.0
W1, W2, W3 = 0.5, 0.2, 0.3
BATTERY_KWH = 60.0
KWH_PER_100KM = 18.0

# Graph / filtering
MAX_CROSS_TRACK_KM = 120.0
MAX_STATIONS_IN_MODEL = 40
M_BIG = 500.0

# Charging economics (placeholders; kW from dataset drives time-per-%)
CHARGE_COST_PER_PCT = 10.0
DC_EFFICIENCY = 0.88


def load_env_dotenv(path: Path | None = None) -> None:
    p = path if path is not None else REPO_ROOT / ".env"
    if not p.is_file():
        return
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            os.environ.setdefault(key, val)


def get_api_key() -> str:
    load_env_dotenv()
    key = os.environ.get("TOMTOM_API_KEY", "").strip()
    if not key:
        print(
            "Set TOMTOM_API_KEY in the environment or in .env at the repo root.\n"
            "Example: export TOMTOM_API_KEY=your_key"
        )
        sys.exit(1)
    return key


def geocode_tomtom(query: str, api_key: str) -> tuple[float, float]:
    q = quote(query.strip(), safe="")
    url = f"{TOMTOM_GEOCODE_BASE}/{q}.json"
    params = {"key": api_key, "countrySet": "TR", "limit": 1}
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    data = r.json()
    results = data.get("results") or []
    if not results:
        raise RuntimeError(f"No TomTom geocode results for: {query!r}")
    pos = results[0].get("position") or {}
    lat, lon = pos.get("lat"), pos.get("lon")
    if lat is None or lon is None:
        raise RuntimeError(f"TomTom geocode missing position for: {query!r}")
    return float(lat), float(lon)


def route_summary_tomtom(
    lat_o: float, lon_o: float, lat_d: float, lon_d: float, api_key: str
) -> tuple[float, float]:
    """Returns (length_km, travel_time_min)."""
    locs = f"{lat_o},{lon_o}:{lat_d},{lon_d}"
    url = f"https://api.tomtom.com/routing/1/calculateRoute/{locs}/json"
    params = {
        "key": api_key,
        "routeRepresentation": "summaryOnly",
        "travelMode": "car",
    }
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    data = r.json()
    routes = data.get("routes") or []
    if not routes:
        raise RuntimeError("TomTom routing returned no routes for Izmir → Ankara.")
    summary = routes[0].get("summary") or {}
    length_m = float(summary.get("lengthInMeters", 0))
    t_sec = float(summary.get("travelTimeInSeconds", 0))
    return length_m / 1000.0, t_sec / 60.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r_earth = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    h = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * r_earth * math.asin(min(1.0, math.sqrt(h)))


def corridor_t_and_cross_km(
    lat0: float,
    lon0: float,
    lat1: float,
    lon1: float,
    latp: float,
    lonp: float,
) -> tuple[float, float]:
    """Local tangent-plane projection: along-track parameter t (0=start, 1=end) and cross-track km."""
    mean_lat = math.radians((lat0 + lat1 + latp) / 3.0)

    def to_xy(lat: float, lon: float) -> tuple[float, float]:
        x = 6371.0 * math.cos(mean_lat) * math.radians(lon - lon0)
        y = 6371.0 * math.radians(lat - lat0)
        return x, y

    x1, y1 = to_xy(lat1, lon1)
    xp, yp = to_xy(latp, lonp)
    dx, dy = x1, y1
    path_len = math.hypot(dx, dy)
    if path_len < 1e-3:
        return 0.0, float("inf")
    t = (xp * dx + yp * dy) / (path_len**2)
    cx = t * dx
    cy = t * dy
    cross = math.hypot(xp - cx, yp - cy)
    return t, cross


def road_km_from_haversine(
    h_km: float, crow_km: float, tom_road_km: float
) -> float:
    if crow_km < 1e-3:
        return 0.0
    return h_km * (tom_road_km / crow_km)


def energy_pct_for_road_km(road_km: float) -> float:
    kwh = (road_km / 100.0) * KWH_PER_100KM
    return (kwh / BATTERY_KWH) * 100.0


def charging_time_min_per_pct(max_kw: float) -> float:
    kw = max(max_kw * DC_EFFICIENCY, 1.0)
    kwh_per_pct = BATTERY_KWH / 100.0
    return (kwh_per_pct / kw) * 60.0


def load_stations_aggregated(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    lat_col, lon_col = "Latitude", "Longitude"
    id_col = "İstasyon No"
    kw_col = "Soket Gücü (kW)"
    name_col = "İstasyon Adı"
    if id_col not in df.columns:
        raise KeyError(f"Expected column {id_col!r} in {csv_path}")
    df = df.dropna(subset=[lat_col, lon_col])
    agg = df.groupby(id_col, as_index=False).agg(
        {
            lat_col: "first",
            lon_col: "first",
            kw_col: "max",
            name_col: "first",
        }
    )
    return agg


def filter_and_sample_stations(
    stations: pd.DataFrame,
    lat_o: float,
    lon_o: float,
    lat_d: float,
    lon_d: float,
) -> pd.DataFrame:
    lat_col, lon_col = "Latitude", "Longitude"
    rows: list[dict[str, float | str]] = []
    for _, r in stations.iterrows():
        lat_s = float(r[lat_col])
        lon_s = float(r[lon_col])
        t, cross = corridor_t_and_cross_km(lat_o, lon_o, lat_d, lon_d, lat_s, lon_s)
        if cross > MAX_CROSS_TRACK_KM or t < -0.08 or t > 1.08:
            continue
        rows.append(
            {
                "t": t,
                "cross_km": cross,
                "lat": lat_s,
                "lon": lon_s,
                "max_kw": float(r["Soket Gücü (kW)"]) if pd.notna(r["Soket Gücü (kW)"]) else 22.0,
                "id": r["İstasyon No"],
                "name": r["İstasyon Adı"] if pd.notna(r["İstasyon Adı"]) else "",
            }
        )
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows).sort_values("t").reset_index(drop=True)
    if len(out) <= MAX_STATIONS_IN_MODEL:
        return out
    nout = len(out)
    m = MAX_STATIONS_IN_MODEL
    take = sorted(
        {
            min(nout - 1, int(round(i * (nout - 1) / max(m - 1, 1))))
            for i in range(m)
        }
    )
    return out.iloc[take].reset_index(drop=True)


def build_edges(
    coords: list[tuple[float, float]],
    tom_road_km: float,
    tom_time_min: float,
) -> dict[tuple[int, int], tuple[float, float]]:
    """Edge (i,j) -> (travel_time_min, energy_pct). Only i < j (forward along trip order)."""
    crow_total = haversine_km(coords[0][0], coords[0][1], coords[-1][0], coords[-1][1])
    edges: dict[tuple[int, int], tuple[float, float]] = {}
    n = len(coords)
    for i in range(n):
        for j in range(i + 1, n):
            h = haversine_km(coords[i][0], coords[i][1], coords[j][0], coords[j][1])
            road = road_km_from_haversine(h, crow_total, tom_road_km)
            e_pct = energy_pct_for_road_km(road)
            if e_pct > B_MAX + 1e-6:
                continue
            if crow_total < 1e-3:
                t_min = 0.0
            else:
                t_min = tom_time_min * (h / crow_total)
            edges[(i, j)] = (t_min, e_pct)
    return edges


def node_charging_params(
    n_nodes: int, station_kw: list[float | None]
) -> dict[int, tuple[float, float]]:
    """
    Returns node_index -> (cost_per_pct, time_min_per_pct).
    Index 0 and n-1 are origin/destination (no charging).
    """
    out: dict[int, tuple[float, float]] = {}
    out[0] = (0.0, 0.0)
    out[n_nodes - 1] = (0.0, 0.0)
    for i in range(1, n_nodes - 1):
        kw = station_kw[i - 1]
        if kw is None or kw <= 0:
            kw = 22.0
        out[i] = (CHARGE_COST_PER_PCT, charging_time_min_per_pct(float(kw)))
    return out


def solve_ev_milp(
    nodes: list[int],
    edges: dict[tuple[int, int], tuple[float, float]],
    node_data: dict[int, tuple[float, float]],
) -> tuple[pulp.LpProblem, dict, dict, dict, dict]:
    prob = pulp.LpProblem("EV_Routing_Izmir_Ankara", pulp.LpMinimize)
    x = pulp.LpVariable.dicts("x", edges.keys(), cat="Binary")
    q = pulp.LpVariable.dicts("q", nodes, lowBound=0, cat="Continuous")
    y = pulp.LpVariable.dicts("y", nodes, lowBound=0, upBound=B_MAX, cat="Continuous")
    p = pulp.LpVariable.dicts("p", nodes, lowBound=0, cat="Continuous")

    prob += (
        W1 * pulp.lpSum(x[ij] * edges[ij][0] for ij in edges)
        + W1 * pulp.lpSum(q[i] * node_data[i][1] for i in nodes)
        + W2 * pulp.lpSum(q[i] * node_data[i][0] for i in nodes)
        + W3 * pulp.lpSum(p[i] for i in nodes)
    )

    start, end = nodes[0], nodes[-1]
    prob += pulp.lpSum(x[start, j] for j in nodes if (start, j) in edges) == 1
    prob += pulp.lpSum(x[i, end] for i in nodes if (i, end) in edges) == 1

    for k in nodes[1:-1]:
        ins = pulp.lpSum(x[i, k] for i in nodes if (i, k) in edges)
        outs = pulp.lpSum(x[k, j] for j in nodes if (k, j) in edges)
        prob += ins == outs

    prob += y[start] == B_START
    for i, j in edges:
        prob += y[j] <= y[i] + q[i] - edges[i, j][1] + M_BIG * (1 - x[i, j])
    for i in nodes:
        prob += y[i] + q[i] <= B_MAX
    for i in nodes:
        prob += p[i] >= THRESHOLD - y[i]

    prob.solve(pulp.PULP_CBC_CMD(msg=False))
    return prob, x, q, y, p


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Izmir→Ankara EV route test: TomTom geocode + route summary, EPDK stations, MILP solve. "
            "Writes the same text shown on stdout to a .txt file by default."
        )
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_TXT,
        help=f"Path to write the report .txt (default: {DEFAULT_OUTPUT_TXT})",
    )
    p.add_argument(
        "--no-output-file",
        action="store_true",
        help="Print to stdout only; do not write a .txt file.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    log = ReportLog()
    api_key = get_api_key()

    log.line("=== Izmir → Ankara EV corridor MILP (TomTom + EPDK) ===")
    log.line(f"Generated (UTC): {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    log.line("")

    log.line("Geocoding origin and destination (TomTom)...")
    lat_o, lon_o = geocode_tomtom(ORIGIN_QUERY, api_key)
    lat_d, lon_d = geocode_tomtom(DEST_QUERY, api_key)
    log.line(f"  Origin:  {ORIGIN_QUERY!r} → ({lat_o:.5f}, {lon_o:.5f})")
    log.line(f"  Dest:    {DEST_QUERY!r} → ({lat_d:.5f}, {lon_d:.5f})")

    log.line("Fetching driving route summary (TomTom)...")
    road_km, drive_min = route_summary_tomtom(lat_o, lon_o, lat_d, lon_d, api_key)
    log.line(
        f"  Road distance: {road_km:.1f} km, travel time: {drive_min:.1f} min (no traffic extras)"
    )

    if not DATA_CSV.is_file():
        log.line(f"Missing dataset: {DATA_CSV}")
        sys.exit(1)

    log.line(f"Loading charging stations from {DATA_CSV.name}...")
    raw = load_stations_aggregated(DATA_CSV)
    corridor = filter_and_sample_stations(raw, lat_o, lon_o, lat_d, lon_d)
    log.line(f"  Stations along corridor (after cap): {len(corridor)}")

    log.line("")
    log.line("--- Model parameters (see script constants) ---")
    log.line(
        f"  B_MAX={B_MAX}, B_START={B_START}, THRESHOLD={THRESHOLD}, "
        f"w1/w2/w3={W1}/{W2}/{W3}, battery_kWh={BATTERY_KWH}, kWh/100km={KWH_PER_100KM}"
    )
    log.line(
        f"  corridor cross-track max={MAX_CROSS_TRACK_KM} km, max stations={MAX_STATIONS_IN_MODEL}"
    )
    log.line("")

    coords: list[tuple[float, float]] = [(lat_o, lon_o)]
    station_kw: list[float | None] = []
    station_meta: list[tuple[str, str]] = []
    for _, r in corridor.iterrows():
        coords.append((float(r["lat"]), float(r["lon"])))
        station_kw.append(float(r["max_kw"]))
        station_meta.append((str(r["id"]), str(r["name"])))
    coords.append((lat_d, lon_d))

    edges = build_edges(coords, road_km, drive_min)
    n = len(coords)
    nodes = list(range(n))
    node_data = node_charging_params(n, station_kw)

    if not any((0, j) in edges for j in nodes):
        log.line("No edges from origin — check coordinates and filters.")
        if not args.no_output_file:
            log.line("")
            log.line(f"(Partial report written to {args.output.resolve()})")
            log.write_file(args.output.resolve())
        sys.exit(1)

    log.line(f"Solving MILP ({n} nodes, {len(edges)} directed forward edges)...")
    prob, x_vars, q_vars, y_vars, p_vars = solve_ev_milp(nodes, edges, node_data)

    status = pulp.LpStatus[prob.status]
    log.line(f"Status: {status}")
    if prob.status != pulp.LpStatusOptimal:
        log.line("No optimal solution — graph may be disconnected under range constraints.")
        if not args.no_output_file:
            log.line("")
            log.line(f"(Partial report written to {args.output.resolve()})")
            log.write_file(args.output.resolve())
        sys.exit(1)

    obj = pulp.value(prob.objective)
    log.line(f"Optimized Z-Score: {obj:.4f}")

    log.line("")
    log.line("--- Route (node indices) ---")
    for i, j in sorted(edges.keys()):
        if pulp.value(x_vars[i, j]) == 1:
            label_i = "ORIGIN" if i == 0 else f"CS {station_meta[i - 1][0]}"
            label_j = "DEST" if j == n - 1 else f"CS {station_meta[j - 1][0]}"
            t_ij, e_ij = edges[i, j]
            log.line(
                f"  {i} → {j}: {label_i} → {label_j} | "
                f"~{t_ij:.1f} min drive, ~{e_ij:.2f}% energy"
            )

    log.line("")
    log.line("--- Charging ---")
    for i in nodes:
        qi = pulp.value(q_vars[i])
        if qi is not None and qi > 1e-6:
            yi = pulp.value(y_vars[i])
            if i == 0:
                loc = "ORIGIN"
            elif i == n - 1:
                loc = "DEST"
            else:
                sid, sname = station_meta[i - 1]
                loc = f"{sid} {sname[:50]}"
            log.line(f"  Charge {qi:.2f}% at node {i} ({loc}), arrived with {yi:.2f}%")

    if not args.no_output_file:
        out_path = args.output.resolve()
        log.line("")
        log.line(f"Full report written to: {out_path}")
        log.write_file(out_path)


if __name__ == "__main__":
    main()
