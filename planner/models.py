"""
Data models for route planning results.
"""
from __future__ import annotations

from dataclasses import dataclass, field


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

    # NOTE: POI-based suggestions will be added once the POI CSV data is ready.
    # The logic skeleton is kept commented in ea_solver.py _build_result.
