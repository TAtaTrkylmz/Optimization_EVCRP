"""
setup — Core modules for the EV Route Planner.
Re-exports key classes and functions for convenient access.
"""

from planner.setup.config import UserPreferences
from planner.setup.models import (
    RouteResult, ChargingStop, LegResult, MultiLegResult,
)
from planner.setup.tomtom import load_api_key, geocode, route_summary
from planner.setup.stations import load_stations, filter_corridor, build_node_list
from planner.setup.matrices import haversine_matrix, build_cost_matrices
from planner.setup import ea_solver
from planner.setup.visualization import (
    show_all_plots
)

__all__ = [
    "UserPreferences",
    "RouteResult", "ChargingStop", "LegResult", "MultiLegResult",
    "load_api_key", "geocode", "route_summary",
    "load_stations", "filter_corridor", "build_node_list",
    "haversine_matrix", "build_cost_matrices",
    "ea_solver",
    "show_all_plots",
]
