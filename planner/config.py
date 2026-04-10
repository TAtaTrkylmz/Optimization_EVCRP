"""
Constants and user preferences for the EV route planner.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


# -- Paths --
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_CSV = REPO_ROOT / "data" / "geocoded_epdk_data.csv"

# -- Battery & cost --
B_MAX = 100.0
ANXIETY_THRESHOLD = 20.0          # penalty kicks in below this SOC (%)
CHARGE_COST_PER_PCT = 10.0        # flat TL per % charged
DC_EFFICIENCY = 0.88

# -- Corridor --
MAX_CROSS_TRACK_KM = 120.0
MAX_STATIONS_IN_MODEL = 40

# -- Evolutionary algorithm --
CHARGE_STEP_PCT = 5               # charge granularity (%)
EA_POP_SIZE = 60
EA_GENERATIONS = 100
EA_MUTATION_RATE = 0.35
EA_CROSSOVER_RATE = 0.6
EA_TOURNAMENT_K = 3

# -- TomTom --
TOMTOM_GEOCODE_BASE = "https://api.tomtom.com/search/2/geocode"


# -- User preferences --

@dataclass
class UserPreferences:
    """All user-configurable inputs for the route planner.

    Priorities are integers 1-5, converted to 0-1 floats by dividing by 5.
    """
    source: str
    destination: str
    battery_start_pct: float
    battery_end_min_pct: float
    battery_capacity_kwh: float = 60.0
    consumption_kwh_per_100km: float = 18.0
    priority_time: int = 3
    priority_cost: int = 3
    priority_anxiety: int = 3
    battery_min_enroute_pct: float = 0.0
    battery_max_enroute_pct: float = 100.0

    # NOTE: external factors (weather, terrain, wind, temperature) will be
    # loaded region-by-region from a CSV in the future.  Not a single scalar.

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
