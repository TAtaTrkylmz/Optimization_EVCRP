"""
planner - Personalizable EV Route Planner
==========================================
Evolutionary algorithm optimizer on a corridor DAG.
Uses TomTom APIs for geocoding/routing and EPDK station data.
Supports multi-destination journeys with ordered waypoints.

Quick start:
    from planner.setup.config import UserPreferences
    from planner.pipeline import plan_journey

    prefs = UserPreferences(
        source="Izmir, Turkey",
        destinations=["Ankara, Turkey"],
        battery_start_pct=85,
        battery_end_min_pct=20,
    )
    result = plan_journey(prefs)
"""

from planner.setup.config import UserPreferences
from planner.setup.models import (
    RouteResult, ChargingStop, LegResult, MultiLegResult,
)
from planner.pipeline import plan_journey
from planner.setup.visualization import (
    plot_route, plot_zscore_convergence,
    plot_multi_leg, plot_multi_leg_convergence,
)

__all__ = [
    "UserPreferences",
    "RouteResult",
    "ChargingStop",
    "LegResult",
    "MultiLegResult",
    "plan_journey",
    "plot_route",
    "plot_zscore_convergence",
    "plot_multi_leg",
    "plot_multi_leg_convergence",
]
