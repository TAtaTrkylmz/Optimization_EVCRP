"""
Personalizable EV Route Planner
================================
NumPy-based forward dynamic programming on a corridor DAG.
Uses TomTom APIs for geocoding/routing and EPDK station data.

Usage via CLI:  python run_planner.py --help
Usage in code:
    from milp.ev_route_planner import EVRoutePlanner, UserPreferences
    prefs = UserPreferences(source="Izmir, Turkey", destination="Ankara, Turkey",
                            battery_start_pct=85, battery_end_min_pct=20)
    planner = EVRoutePlanner(prefs)
    results = planner.plan_route()
"""
from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import numpy as np
import pandas as pd
import requests

# ─── Paths & Constants ───────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_CSV = REPO_ROOT / "data" / "geocoded_epdk_data.csv"

B_MAX = 100.0
ANXIETY_THRESHOLD = 20.0
CHARGE_COST_PER_PCT = 10.0        # flat TL per % charged
DC_EFFICIENCY = 0.88
MAX_CROSS_TRACK_KM = 120.0
MAX_STATIONS_IN_MODEL = 40
CHARGE_STEP_PCT = 5                # DP charge granularity (%)
TOMTOM_GEOCODE_BASE = "https://api.tomtom.com/search/2/geocode"


# ─── Data Classes ────────────────────────────────────────────────────────

@dataclass
class UserPreferences:
    """All user-configurable inputs for the route planner.

    Priorities are integers 1-5, converted to 0-1 floats by dividing by 5.
    """
    source: str
    destination: str
    battery_start_pct: float            # current battery %
    battery_end_min_pct: float          # desired ending battery %
    battery_capacity_kwh: float = 60.0
    consumption_kwh_per_100km: float = 18.0
    priority_time: int = 3              # 1–5
    priority_cost: int = 3              # 1–5
    priority_anxiety: int = 3           # 1–5

    # ── Enroute battery bounds ──
    battery_min_enroute_pct: float = 0.0   # never drop below this %
    battery_max_enroute_pct: float = 100.0 # never charge above this %

    # ── External factors ──
    external_factor: float = 1.0
    """Multiplier on energy consumption.  >1 = harder conditions
    (e.g. rain/snow, strong headwind, steep terrain, cold weather).
    <1 = favourable conditions (tailwind, flat, mild weather).
    Default 1.0 = nominal."""

    @property
    def w_time(self) -> float:
        return self.priority_time / 5.0

    @property
    def w_cost(self) -> float:
        return self.priority_cost / 5.0

    @property
    def w_anxiety(self) -> float:
        return self.priority_anxiety / 5.0

    def __post_init__(self):
        for attr in ("priority_time", "priority_cost", "priority_anxiety"):
            v = getattr(self, attr)
            if not (1 <= v <= 5):
                raise ValueError(f"{attr} must be between 1 and 5, got {v}")
        if not (0 <= self.battery_start_pct <= 100):
            raise ValueError("battery_start_pct must be 0-100")
        if not (0 <= self.battery_end_min_pct <= 100):
            raise ValueError("battery_end_min_pct must be 0-100")
        if not (0 <= self.battery_min_enroute_pct <= 100):
            raise ValueError("battery_min_enroute_pct must be 0-100")
        if not (0 <= self.battery_max_enroute_pct <= 100):
            raise ValueError("battery_max_enroute_pct must be 0-100")
        if self.battery_min_enroute_pct > self.battery_max_enroute_pct:
            raise ValueError("battery_min_enroute_pct must be <= battery_max_enroute_pct")
        if self.external_factor <= 0:
            raise ValueError("external_factor must be > 0")


@dataclass
class ChargingStop:
    """Details of a single charging stop along the route."""
    node_index: int
    station_id: str
    station_name: str
    lat: float
    lon: float
    max_kw: float
    battery_on_arrival_pct: float
    charge_amount_pct: float
    battery_on_departure_pct: float
    charge_time_min: float
    charge_cost: float


@dataclass
class Suggestion:
    """A contextual suggestion for a charging stop."""
    station_name: str
    charge_time_min: float
    message: str
    pois: list[dict] = field(default_factory=list)


@dataclass
class RouteResult:
    """Complete result for one candidate route."""
    rank: int
    path_node_indices: list[int]
    stops: list[ChargingStop]
    total_drive_time_min: float
    total_charge_time_min: float
    total_time_min: float
    total_cost: float
    z_score: float
    battery_at_destination_pct: float
    suggestions: list[Suggestion] = field(default_factory=list)


# ─── Mock POI Database (replace with TomTom POI Search later) ────────────
MOCK_POIS = [
    {"name": "Highway Rest Area & Market", "type": "rest_area", "distance_m": 120},
    {"name": "Petrol Ofisi Road Restaurant", "type": "restaurant", "distance_m": 250},
    {"name": "Kahve Dunyasi", "type": "cafe", "distance_m": 180},
    {"name": "Migros Jet", "type": "supermarket", "distance_m": 350},
    {"name": "Burger King Drive-Through", "type": "fast_food", "distance_m": 400},
]


# ─── Planner ─────────────────────────────────────────────────────────────

class EVRoutePlanner:
    """
    NumPy-based EV route planner with personalizable preferences.

    Uses forward dynamic programming on a corridor DAG built from
    EPDK charging station data and TomTom routing.
    """

    def __init__(self, prefs: UserPreferences):
        self.prefs = prefs
        self._api_key: Optional[str] = None
        # Populated by plan_route() for use by plot_route()
        self._coords: list[tuple[float, float]] = []
        self._station_meta: list[tuple[str, str]] = []
        self._dist_mat: np.ndarray | None = None
        self._road_factor: float = 1.0

    # ── Public API ────────────────────────────────────────────────────

    def plan_route(self) -> list[RouteResult]:
        """Run the full planning pipeline.  Returns up to 3 ranked routes."""
        api_key = self._get_api_key()

        print(f"[1/6] Geocoding source: {self.prefs.source!r}")
        lat_o, lon_o = self._geocode(self.prefs.source, api_key)
        print(f"       -> ({lat_o:.5f}, {lon_o:.5f})")

        print(f"[2/6] Geocoding destination: {self.prefs.destination!r}")
        lat_d, lon_d = self._geocode(self.prefs.destination, api_key)
        print(f"       -> ({lat_d:.5f}, {lon_d:.5f})")

        print("[3/6] Fetching driving route from TomTom...")
        road_km, drive_min = self._route_summary(lat_o, lon_o, lat_d, lon_d, api_key)
        print(f"       -> {road_km:.1f} km, {drive_min:.1f} min")

        print("[4/6] Loading & filtering charging stations...")
        stations = self._load_stations()
        corridor_df = self._filter_corridor(stations, lat_o, lon_o, lat_d, lon_d)
        print(f"       -> {len(corridor_df)} stations in corridor")
        if corridor_df.empty:
            print("WARNING: No charging stations found along the corridor!")
            return []

        print("[5/6] Building NumPy distance / energy / time matrices...")
        coords, station_kw, station_meta = self._build_node_list(
            lat_o, lon_o, lat_d, lon_d, corridor_df,
        )
        n = len(coords)
        coords_np = np.array(coords)
        dist_mat = self._haversine_matrix(coords_np)
        crow_total = float(dist_mat[0, n - 1])
        road_factor = road_km / max(crow_total, 1e-3)
        energy_mat = self._energy_matrix(dist_mat, road_factor)
        time_mat = self._time_matrix(dist_mat, crow_total, drive_min)
        print(f"       -> {n} nodes, matrices shape {dist_mat.shape}")

        print("[6/6] Running forward DP optimisation...")
        # station_kw array: index 0 = origin (0), 1..N = stations, N+1 = dest (0)
        kw_arr = np.array([0.0] + station_kw + [0.0])
        results = self._find_top_routes(
            n, energy_mat, time_mat, kw_arr, station_meta, coords,
        )
        print(f"       -> Found {len(results)} route(s)\n")

        # Store internals for plotting
        self._coords = coords
        self._station_meta = station_meta
        self._dist_mat = dist_mat
        self._road_factor = road_factor

        return results

    # ── TomTom helpers ────────────────────────────────────────────────

    def _get_api_key(self) -> str:
        if self._api_key:
            return self._api_key
        env_path = REPO_ROOT / ".env"
        if env_path.is_file():
            with open(env_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))
        key = os.environ.get("TOMTOM_API_KEY", "").strip()
        if not key:
            print("Set TOMTOM_API_KEY in .env at repo root.")
            sys.exit(1)
        self._api_key = key
        return key

    @staticmethod
    def _geocode(query: str, api_key: str) -> tuple[float, float]:
        q = quote(query.strip(), safe="")
        url = f"{TOMTOM_GEOCODE_BASE}/{q}.json"
        params = {"key": api_key, "countrySet": "TR", "limit": 1}
        r = requests.get(url, params=params, timeout=60)
        r.raise_for_status()
        results = r.json().get("results") or []
        if not results:
            raise RuntimeError(f"No geocode results for: {query!r}")
        pos = results[0].get("position", {})
        lat, lon = pos.get("lat"), pos.get("lon")
        if lat is None or lon is None:
            raise RuntimeError(f"Geocode missing position for: {query!r}")
        return float(lat), float(lon)

    @staticmethod
    def _route_summary(
        lat_o: float, lon_o: float, lat_d: float, lon_d: float, api_key: str,
    ) -> tuple[float, float]:
        """Returns (road_km, drive_min)."""
        locs = f"{lat_o},{lon_o}:{lat_d},{lon_d}"
        url = f"https://api.tomtom.com/routing/1/calculateRoute/{locs}/json"
        params = {"key": api_key, "routeRepresentation": "summaryOnly", "travelMode": "car"}
        r = requests.get(url, params=params, timeout=60)
        r.raise_for_status()
        routes = r.json().get("routes") or []
        if not routes:
            raise RuntimeError("TomTom returned no routes.")
        s = routes[0].get("summary", {})
        return float(s.get("lengthInMeters", 0)) / 1000.0, float(s.get("travelTimeInSeconds", 0)) / 60.0

    # ── Station data ──────────────────────────────────────────────────

    @staticmethod
    def _load_stations() -> pd.DataFrame:
        if not DATA_CSV.is_file():
            raise FileNotFoundError(f"Missing station data: {DATA_CSV}")
        df = pd.read_csv(DATA_CSV)
        df = df.dropna(subset=["Latitude", "Longitude"])
        return df.groupby("İstasyon No", as_index=False).agg({
            "Latitude": "first", "Longitude": "first",
            "Soket Gücü (kW)": "max", "İstasyon Adı": "first",
        })

    @staticmethod
    def _filter_corridor(
        stations: pd.DataFrame,
        lat_o: float, lon_o: float, lat_d: float, lon_d: float,
    ) -> pd.DataFrame:
        """NumPy-vectorised corridor filter + sampling."""
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
            kw = float(r["Soket Gücü (kW)"]) if pd.notna(r["Soket Gücü (kW)"]) else 22.0
            rows.append({
                "t": float(t[idx]), "cross_km": float(cross_km[idx]),
                "lat": float(r["Latitude"]), "lon": float(r["Longitude"]),
                "max_kw": kw, "id": r["İstasyon No"],
                "name": r["İstasyon Adı"] if pd.notna(r["İstasyon Adı"]) else "",
            })
        if not rows:
            return pd.DataFrame()
        out = pd.DataFrame(rows).sort_values("t").reset_index(drop=True)
        if len(out) <= MAX_STATIONS_IN_MODEL:
            return out
        nout = len(out)
        m = MAX_STATIONS_IN_MODEL
        indices = sorted({min(nout - 1, int(round(i * (nout - 1) / max(m - 1, 1)))) for i in range(m)})
        return out.iloc[indices].reset_index(drop=True)

    # ── NumPy graph matrices ──────────────────────────────────────────

    @staticmethod
    def _build_node_list(lat_o, lon_o, lat_d, lon_d, corridor_df):
        coords = [(lat_o, lon_o)]
        station_kw, station_meta = [], []
        for _, r in corridor_df.iterrows():
            coords.append((float(r["lat"]), float(r["lon"])))
            station_kw.append(float(r["max_kw"]))
            station_meta.append((str(r["id"]), str(r["name"])))
        coords.append((lat_d, lon_d))
        return coords, station_kw, station_meta

    @staticmethod
    def _haversine_matrix(coords: np.ndarray) -> np.ndarray:
        """Vectorised pairwise haversine (km)."""
        lat = np.radians(coords[:, 0])
        lon = np.radians(coords[:, 1])
        dlat = lat[:, None] - lat[None, :]
        dlon = lon[:, None] - lon[None, :]
        h = np.sin(dlat / 2) ** 2 + np.cos(lat[:, None]) * np.cos(lat[None, :]) * np.sin(dlon / 2) ** 2
        return 2 * 6371.0 * np.arcsin(np.minimum(1.0, np.sqrt(h)))

    def _energy_matrix(self, dist_mat: np.ndarray, road_factor: float) -> np.ndarray:
        """Energy cost (%) for each node pair, scaled by external_factor."""
        road_km = dist_mat * road_factor
        kwh = (road_km / 100.0) * self.prefs.consumption_kwh_per_100km
        base_pct = (kwh / self.prefs.battery_capacity_kwh) * 100.0
        return base_pct * self.prefs.external_factor

    @staticmethod
    def _time_matrix(dist_mat: np.ndarray, crow_total: float, drive_min: float) -> np.ndarray:
        """Travel time (min) scaled from TomTom total."""
        if crow_total < 1e-3:
            return np.zeros_like(dist_mat)
        return dist_mat * (drive_min / crow_total)

    # ── Forward DP ────────────────────────────────────────────────────

    def _charge_time_min(self, charge_pct: float, max_kw: float) -> float:
        if charge_pct <= 0 or max_kw <= 0:
            return 0.0
        kw_eff = max(max_kw * DC_EFFICIENCY, 1.0)
        kwh = (charge_pct / 100.0) * self.prefs.battery_capacity_kwh
        return (kwh / kw_eff) * 60.0

    def _forward_dp(
        self, n: int, energy_mat: np.ndarray, time_mat: np.ndarray,
        station_kw: np.ndarray, exclude: set[int] | None = None,
    ) -> tuple[list[int] | None, dict[int, float] | None, float]:
        """
        Forward DP on corridor DAG.
        State: (node, battery_level_int).  Battery discretised to 1 %.
        Returns (path, charges_dict, z_score) or (None, None, inf).
        """
        B = int(B_MAX) + 1
        INF = float("inf")
        exclude = exclude or set()
        w_t, w_c, w_a = self.prefs.w_time, self.prefs.w_cost, self.prefs.w_anxiety
        b_floor = int(round(self.prefs.battery_min_enroute_pct))
        b_ceil  = int(round(self.prefs.battery_max_enroute_pct))

        dp = np.full((n, B), INF)
        pred: list[list[tuple[int, int, int] | None]] = [[None] * B for _ in range(n)]

        b_start = int(round(min(self.prefs.battery_start_pct, B_MAX)))
        dp[0][b_start] = 0.0

        for i in range(n):
            if i in exclude:
                continue
            for b in range(B):
                if dp[i][b] >= INF:
                    continue
                # charge options (capped at enroute ceiling)
                if 0 < i < n - 1:
                    max_q = min(int(B_MAX), b_ceil) - b
                    if max_q < 0:
                        max_q = 0
                    charges = list(range(0, max_q + 1, CHARGE_STEP_PCT))
                    if max_q > 0 and max_q not in charges:
                        charges.append(max_q)
                else:
                    charges = [0]

                for q in charges:
                    b_depart = b + q
                    ct = self._charge_time_min(q, float(station_kw[i]))
                    cc = q * CHARGE_COST_PER_PCT

                    for j in range(i + 1, n):
                        if j in exclude and j != n - 1:
                            continue
                        e_ij = energy_mat[i, j]
                        if e_ij > B_MAX:
                            continue
                        b_arrive_f = b_depart - e_ij
                        if b_arrive_f < b_floor - 0.5:
                            continue
                        b_arr = max(0, min(int(B_MAX), int(round(b_arrive_f))))

                        # enforce enroute floor constraint (on discrete level)
                        if b_arr < b_floor:
                            continue

                        anxiety = max(0.0, ANXIETY_THRESHOLD - b_arrive_f)
                        cost = w_t * (time_mat[i, j] + ct) + w_c * cc + w_a * anxiety
                        total = dp[i][b] + cost
                        if total < dp[j][b_arr]:
                            dp[j][b_arr] = total
                            pred[j][b_arr] = (i, b, q)

        # best arrival at destination with battery >= end target
        dest = n - 1
        b_end = int(round(self.prefs.battery_end_min_pct))
        best_b, best_cost = -1, INF
        for b in range(b_end, B):
            if dp[dest][b] < best_cost:
                best_cost = dp[dest][b]
                best_b = b

        if best_b < 0 or best_cost >= INF:
            return None, None, INF

        # reconstruct
        path: list[int] = []
        charges_map: dict[int, float] = {}
        node, bat = dest, best_b
        while True:
            path.append(node)
            p = pred[node][bat]
            if p is None:
                break
            pn, pb, pq = p
            if pq > 0:
                charges_map[pn] = float(pq)
            node, bat = pn, pb
        path.reverse()
        return path, charges_map, best_cost

    # ── Top-3 routes ──────────────────────────────────────────────────

    def _find_top_routes(
        self, n, energy_mat, time_mat, station_kw, station_meta, coords,
    ) -> list[RouteResult]:
        results: list[RouteResult] = []
        used: set[tuple[int, ...]] = set()

        path, charges, z = self._forward_dp(n, energy_mat, time_mat, station_kw)
        if path:
            used.add(tuple(path))
            results.append(self._build_result(1, path, charges, energy_mat, time_mat, station_kw, station_meta, coords))

            # alternatives: exclude each intermediate station in the best path
            for exc in [nd for nd in path if 0 < nd < n - 1]:
                if len(results) >= 3:
                    break
                ap, ac, az = self._forward_dp(n, energy_mat, time_mat, station_kw, exclude={exc})
                if ap and tuple(ap) not in used:
                    used.add(tuple(ap))
                    results.append(self._build_result(len(results) + 1, ap, ac, energy_mat, time_mat, station_kw, station_meta, coords))

        results.sort(key=lambda r: r.z_score)
        for i, r in enumerate(results):
            r.rank = i + 1
        return results[:3]

    # ── Result builder ────────────────────────────────────────────────

    def _build_result(self, rank, path, charges, energy_mat, time_mat, station_kw, station_meta, coords):
        n = len(coords)
        stops: list[ChargingStop] = []
        total_drive = total_ct = total_cc = 0.0
        battery = self.prefs.battery_start_pct

        for step in range(len(path) - 1):
            i, j = path[step], path[step + 1]
            q = charges.get(i, 0)
            if 0 < i < n and q > 0:
                kw = float(station_kw[i])
                ct = self._charge_time_min(q, kw)
                cc = q * CHARGE_COST_PER_PCT
                sid, sname = station_meta[i - 1]
                stops.append(ChargingStop(
                    node_index=i, station_id=sid,
                    station_name=sname[:60] if sname else f"Station {sid}",
                    lat=coords[i][0], lon=coords[i][1], max_kw=kw,
                    battery_on_arrival_pct=round(battery, 1),
                    charge_amount_pct=round(q, 1),
                    battery_on_departure_pct=round(battery + q, 1),
                    charge_time_min=round(ct, 1), charge_cost=round(cc, 1),
                ))
                total_ct += ct
                total_cc += cc
                battery += q
            battery -= energy_mat[i, j]
            total_drive += time_mat[i, j]

        suggestions = self._generate_suggestions(stops)
        z = (self.prefs.w_time * (total_drive + total_ct)
             + self.prefs.w_cost * total_cc
             + self.prefs.w_anxiety * sum(max(0, ANXIETY_THRESHOLD - s.battery_on_arrival_pct) for s in stops))

        return RouteResult(
            rank=rank, path_node_indices=path, stops=stops,
            total_drive_time_min=round(total_drive, 1),
            total_charge_time_min=round(total_ct, 1),
            total_time_min=round(total_drive + total_ct, 1),
            total_cost=round(total_cc, 1), z_score=round(z, 2),
            battery_at_destination_pct=round(max(0, battery), 1),
            suggestions=suggestions,
        )

    # ── Suggestions (mock POIs) ───────────────────────────────────────

    @staticmethod
    def _generate_suggestions(stops: list[ChargingStop]) -> list[Suggestion]:
        suggestions: list[Suggestion] = []
        for stop in stops:
            ct = stop.charge_time_min
            if ct < 5:
                suggestions.append(Suggestion(
                    station_name=stop.station_name, charge_time_min=ct,
                    message=f"Quick top-up at {stop.station_name} ({ct:.0f} min). No need to leave the car.",
                    pois=[],
                ))
            elif ct < 20:
                pois = MOCK_POIS[:2]
                suggestions.append(Suggestion(
                    station_name=stop.station_name, charge_time_min=ct,
                    message=(f"Moderate charge at {stop.station_name} ({ct:.0f} min). "
                             f"Grab a snack at {pois[1]['name']} ({pois[1]['distance_m']}m away)."),
                    pois=pois,
                ))
            else:
                pois = MOCK_POIS[:4]
                suggestions.append(Suggestion(
                    station_name=stop.station_name, charge_time_min=ct,
                    message=(f"Extended charge at {stop.station_name} ({ct:.0f} min). "
                             f"Great time for a meal at {pois[1]['name']} ({pois[1]['distance_m']}m) "
                             f"or coffee at {pois[2]['name']} ({pois[2]['distance_m']}m)."),
                    pois=pois,
                ))
        return suggestions


# ─── Pretty-print helper ────────────────────────────────────────────────

def format_route(result: RouteResult, prefs: UserPreferences) -> str:
    """Format a RouteResult as a human-readable string."""
    lines = [
        f"{'='*60}",
        f"  Route #{result.rank}   (Z-score: {result.z_score:.2f})",
        f"{'='*60}",
        f"  Weights  ->  time={prefs.w_time:.1f}  cost={prefs.w_cost:.1f}  anxiety={prefs.w_anxiety:.1f}",
        f"  External factor : {prefs.external_factor:.2f}",
        f"  Enroute bounds  : floor={prefs.battery_min_enroute_pct:.0f}%  ceil={prefs.battery_max_enroute_pct:.0f}%",
        f"  Drive time      : {result.total_drive_time_min:.1f} min",
        f"  Charge time     : {result.total_charge_time_min:.1f} min",
        f"  Total time      : {result.total_time_min:.1f} min",
        f"  Total cost      : {result.total_cost:.1f} TL",
        f"  Battery at dest : {result.battery_at_destination_pct:.1f}%",
        "",
    ]
    if result.stops:
        lines.append("  Charging Stops:")
        for s in result.stops:
            lines.append(
                f"    * {s.station_name}  (ID {s.station_id}, {s.max_kw:.0f} kW)\n"
                f"      Arrive {s.battery_on_arrival_pct:.1f}% -> charge {s.charge_amount_pct:.1f}% "
                f"-> depart {s.battery_on_departure_pct:.1f}%  ({s.charge_time_min:.1f} min, {s.charge_cost:.1f} TL)"
            )
        lines.append("")
    else:
        lines.append("  No charging stops needed — direct drive!\n")

    if result.suggestions:
        lines.append("  Suggestions:")
        for sg in result.suggestions:
            lines.append(f"    - {sg.message}")
        lines.append("")

    return "\n".join(lines)


# ─── Route Visualisation (matplotlib) ────────────────────────────────────

def plot_route(
    result: RouteResult,
    prefs: UserPreferences,
    coords: list[tuple[float, float]],
    station_meta: list[tuple[str, str]],
    dist_mat: np.ndarray,
    road_factor: float,
    save_path: Path | str | None = None,
    show: bool = True,
) -> None:
    """
    Draw a single route on a lat/lon scatter plot.

    - Origin  = green ★
    - Destination = red ■
    - Charging stops on this route = blue ● (labelled)
    - Other corridor stations = small grey ·
    - Arrows between consecutive route nodes with road-km labels
    """
    import matplotlib.pyplot as plt
    import matplotlib.patheffects as pe

    n = len(coords)
    all_lons = [c[1] for c in coords]
    all_lats = [c[0] for c in coords]

    # Nodes on the route path
    path = result.path_node_indices
    path_set = set(path)
    stop_indices = {s.node_index for s in result.stops}

    fig, ax = plt.subplots(figsize=(14, 8))

    # ── 1. Draw all corridor stations (grey, background) ─────────────
    for i in range(1, n - 1):
        if i not in path_set:
            ax.plot(coords[i][1], coords[i][0], ".", color="#cccccc",
                    markersize=5, zorder=1)

    # ── 2. Draw route arrows ─────────────────────────────────────────
    for step in range(len(path) - 1):
        i, j = path[step], path[step + 1]
        xi, yi = coords[i][1], coords[i][0]
        xj, yj = coords[j][1], coords[j][0]
        road_km = dist_mat[i, j] * road_factor

        ax.annotate(
            "",
            xy=(xj, yj), xytext=(xi, yi),
            arrowprops=dict(
                arrowstyle="-|>",
                color="#2563EB",
                lw=2.0,
                shrinkA=8, shrinkB=8,
                connectionstyle="arc3,rad=0.08",
            ),
            zorder=2,
        )
        # distance label at midpoint
        mx = (xi + xj) / 2
        my = (yi + yj) / 2
        ax.text(
            mx, my, f"{road_km:.0f} km",
            fontsize=7, color="#1e40af", fontweight="bold",
            ha="center", va="bottom",
            bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.8),
            zorder=5,
        )

    # ── 3. Draw nodes ────────────────────────────────────────────────
    text_outline = [pe.withStroke(linewidth=2.5, foreground="white")]

    # Origin
    ax.plot(coords[0][1], coords[0][0], marker="*", color="#16a34a",
            markersize=20, zorder=10, markeredgecolor="white", markeredgewidth=0.8)
    ax.annotate(
        f"{prefs.source}\n({coords[0][0]:.4f}, {coords[0][1]:.4f})",
        xy=(coords[0][1], coords[0][0]),
        xytext=(12, -18), textcoords="offset points",
        fontsize=8, fontweight="bold", color="#166534",
        path_effects=text_outline, zorder=11,
    )

    # Destination
    ax.plot(coords[-1][1], coords[-1][0], marker="s", color="#dc2626",
            markersize=14, zorder=10, markeredgecolor="white", markeredgewidth=0.8)
    ax.annotate(
        f"{prefs.destination}\n({coords[-1][0]:.4f}, {coords[-1][1]:.4f})",
        xy=(coords[-1][1], coords[-1][0]),
        xytext=(-12, 14), textcoords="offset points",
        fontsize=8, fontweight="bold", color="#991b1b",
        ha="right", va="bottom",
        path_effects=text_outline, zorder=11,
    )

    # Charging stops — alternate label above / below to reduce overlap
    for si, s in enumerate(result.stops):
        i = s.node_index
        ax.plot(coords[i][1], coords[i][0], "o", color="#2563EB",
                markersize=10, zorder=10, markeredgecolor="white", markeredgewidth=0.8)
        name_short = s.station_name[:25]
        label = (f"{name_short}\n"
                 f"({coords[i][0]:.4f}, {coords[i][1]:.4f})\n"
                 f"+{s.charge_amount_pct:.0f}%  {s.charge_time_min:.0f}min")
        y_off = 14 if si % 2 == 0 else -14
        va = "bottom" if si % 2 == 0 else "top"
        ax.annotate(
            label, xy=(coords[i][1], coords[i][0]),
            xytext=(8, y_off), textcoords="offset points",
            fontsize=6.5, color="#1e3a5f", va=va,
            path_effects=text_outline, zorder=11,
        )

    # Route-through nodes that are NOT charging (passed through with 0 charge)
    for idx in path:
        if idx == 0 or idx == n - 1 or idx in stop_indices:
            continue
        ax.plot(coords[idx][1], coords[idx][0], "D", color="#f59e0b",
                markersize=7, zorder=9, markeredgecolor="white", markeredgewidth=0.5)

    # ── 4. Styling ───────────────────────────────────────────────────
    pad_lon = (max(all_lons) - min(all_lons)) * 0.12 + 0.2
    pad_lat = (max(all_lats) - min(all_lats)) * 0.12 + 0.1
    ax.set_xlim(min(all_lons) - pad_lon, max(all_lons) + pad_lon)
    ax.set_ylim(min(all_lats) - pad_lat, max(all_lats) + pad_lat)
    ax.set_xlabel("Longitude", fontsize=10)
    ax.set_ylabel("Latitude", fontsize=10)
    ax.set_title(
        f"Route #{result.rank}:  {prefs.source} → {prefs.destination}\n"
        f"Z={result.z_score:.1f}  |  {result.total_time_min:.0f} min  |  "
        f"{result.total_cost:.0f} TL  |  dest SOC {result.battery_at_destination_pct:.0f}%",
        fontsize=11, fontweight="bold",
    )
    ax.grid(True, alpha=0.3, linestyle="--")

    # Legend
    from matplotlib.lines import Line2D
    legend_elems = [
        Line2D([0], [0], marker="*", color="w", markerfacecolor="#16a34a",
               markersize=14, label="Origin"),
        Line2D([0], [0], marker="s", color="w", markerfacecolor="#dc2626",
               markersize=10, label="Destination"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#2563EB",
               markersize=9, label="Charging Stop"),
        Line2D([0], [0], marker=".", color="w", markerfacecolor="#cccccc",
               markersize=8, label="Corridor Station (unused)"),
    ]
    ax.legend(handles=legend_elems, loc="lower left", fontsize=8,
              framealpha=0.9)

    fig.tight_layout()

    if save_path:
        p = Path(save_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(str(p), dpi=150, bbox_inches="tight")
        print(f"Plot saved: {p.resolve()}")
    if show:
        plt.show()
    else:
        plt.close(fig)


def plot_all_routes(
    results: list[RouteResult],
    prefs: UserPreferences,
    planner: "EVRoutePlanner",
    save_dir: Path | str | None = None,
    show: bool = True,
) -> None:
    """Plot each route result, optionally saving PNGs to save_dir."""
    if not planner._coords:
        print("No graph data — call planner.plan_route() first.")
        return
    for r in results:
        save_path = None
        if save_dir:
            d = Path(save_dir)
            save_path = d / f"route_{r.rank}.png"
        plot_route(
            r, prefs,
            planner._coords, planner._station_meta,
            planner._dist_mat, planner._road_factor,
            save_path=save_path, show=show,
        )
