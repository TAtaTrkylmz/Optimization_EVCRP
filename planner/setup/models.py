"""
Data models for route planning results.

RouteResult  — a single source-to-destination leg solution
LegResult    — wraps RouteResult with per-leg metadata for multi-leg journeys
MultiLegResult — aggregation over all legs
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
    wait_time_min: float = 0.0
    arrival_time_min: float = 0.0
    departure_time_min: float = 0.0


@dataclass
class RouteResult:
    """Complete result for one candidate route (single leg)."""
    rank: int
    path_node_indices: list[int]
    stops: list[ChargingStop]
    total_drive_time_min: float
    total_charge_time_min: float
    total_wait_time_min: float
    total_time_min: float
    total_cost: float
    total_distance_km: float
    z_score: float
    battery_at_destination_pct: float
    is_partial: bool = False            # True when route couldn't reach destination

    # NOTE: POI-based suggestions will be added once the POI CSV data is ready.
    # The logic skeleton is kept commented in ea_solver.py _build_result.


@dataclass
class LegResult:
    """One leg of a multi-destination journey with visual data."""
    leg_index: int                         # 0-based
    origin: str                            # human-readable name
    destination: str                       # human-readable name
    route: RouteResult
    convergence: list[float]               # best Z per generation
    feasible_routes_found: int = 0         # number of valid routes found by the EA solver
    # Data needed for visualization (kept as generic types)
    coords: Any = None                     # list[tuple[float, float]]
    station_meta: Any = None               # list[tuple[str, str]]
    dist_mat: Any = None                   # np.ndarray
    road_km_mat: Any = None                # np.ndarray — real road km per edge
    road_factor: float = 1.0
    route_geometries: Any = None           # dict[(i,j)] -> list[(lat,lon)] road polylines


@dataclass
class MultiLegResult:
    """Aggregated result for the entire multi-leg journey."""
    legs: list[LegResult]
    weather_squares: list = field(default_factory=list)  # list[WeatherSquare] from mocker

    @property
    def total_drive_time_min(self) -> float:
        return sum(leg.route.total_drive_time_min for leg in self.legs)

    @property
    def total_charge_time_min(self) -> float:
        return sum(leg.route.total_charge_time_min for leg in self.legs)

    @property
    def total_wait_time_min(self) -> float:
        return sum(getattr(leg.route, 'total_wait_time_min', 0.0) for leg in self.legs)

    @property
    def total_time_min(self) -> float:
        return self.total_drive_time_min + self.total_charge_time_min + self.total_wait_time_min

    @property
    def total_cost(self) -> float:
        return sum(leg.route.total_cost for leg in self.legs)

    @property
    def total_z_score(self) -> float:
        return sum(leg.route.z_score for leg in self.legs)

    @property
    def total_distance_km(self) -> float:
        return sum(leg.route.total_distance_km for leg in self.legs)

    @property
    def battery_at_final_dest(self) -> float:
        return self.legs[-1].route.battery_at_destination_pct

    @property
    def itinerary(self) -> str:
        """Full itinerary string, e.g. 'Izmir -> Balikesir -> Ankara'."""
        names = [self.legs[0].origin]
        for leg in self.legs:
            names.append(leg.destination)
        return " -> ".join(names)
