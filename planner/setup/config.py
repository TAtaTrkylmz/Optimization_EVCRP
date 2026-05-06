"""
Constants and user preferences for the EV route planner.

Velocity model:
    Energy is ALWAYS computed at eco speed (BASE_VELOCITY_KMH = 70 km/h)
    to ensure maximum range and route feasibility.

    Time is computed at CRUISE speed (CRUISE_VELOCITY_KMH = 90 km/h)
    or from real-world TomTom data when available.

    This decoupling ensures:
    - Feasibility is never affected by user weights
    - The Z-score correctly captures the time/cost/anxiety tradeoff
    - All physically possible routes are found by the EA

DESIGN RULE: Priorities ONLY PRIORITIZE — they never CONTROL the physics.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


# ── Paths ──
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_CSV = REPO_ROOT / "data" / "geocoded_epdk_data.csv"

# ── Battery & cost ──
B_MAX = 100.0
ANXIETY_THRESHOLD = 20.0          # penalty kicks in below this SOC (%)
CHARGE_COST_PER_PCT = 10.0        # flat TL per % charged
DC_EFFICIENCY = 0.88

# ── Velocity ──
BASE_VELOCITY_KMH = 70.0         # eco speed — used for ENERGY computation
CRUISE_VELOCITY_KMH = 90.0       # cruise speed — used for TIME computation
VELOCITY_EXPONENT = 1.6           # drag exponent for consumption scaling

# ── Corridor ──
MAX_CROSS_TRACK_KM = 120.0
MAX_STATIONS_IN_MODEL = 40

# ── Evolutionary algorithm ──
CHARGE_STEP_PCT = 5               # charge granularity (%)
EA_POP_SIZE = 60
EA_GENERATIONS = 300
EA_MUTATION_RATE = 0.35
EA_CROSSOVER_RATE = 0.6
EA_TOURNAMENT_K = 3

# ── TomTom ──
TOMTOM_GEOCODE_BASE = "https://api.tomtom.com/search/2/geocode"


# ── User preferences ──

@dataclass
class UserPreferences:
    """All user-configurable inputs for the route planner.

    Priorities are integers 1-5, converted to 0-1 floats by dividing by 5.
    destinations is an ordered list — visited in the given sequence.

    DESIGN RULE — priorities only PRIORITIZE, they never CONTROL:
        priority_time    -> Z-score weight only
        priority_cost    -> Z-score weight only
        priority_anxiety -> Z-score weight only

    Velocity is NOT a user preference:
        Energy  -> always at eco speed (70 km/h) for max feasibility
        Time    -> at cruise speed (90 km/h) or TomTom real-world data
    """
    source: str
    destinations: list[str]            # ordered waypoints, last = final dest
    battery_start_pct: float
    battery_end_min_pct: float
    battery_capacity_kwh: float = 60.0
    consumption_kwh_per_100km: float = 22.0
    priority_time: int = 3
    priority_cost: int = 3
    priority_anxiety: int = 3
    battery_min_enroute_pct: float = 0.0
    battery_max_enroute_pct: float = 100.0

    # NOTE: external factors (weather, terrain, wind, temperature) will be
    # loaded region-by-region from a CSV in the future.  Not a single scalar.

    # ── Derived properties ──

    @property
    def final_destination(self) -> str:
        """Last destination in the ordered list."""
        return self.destinations[-1]

    @property
    def w_time(self) -> float:
        return self.priority_time / 5.0

    @property
    def w_cost(self) -> float:
        return self.priority_cost / 5.0

    @property
    def w_anxiety(self) -> float:
        return self.priority_anxiety / 5.0

    @property
    def velocity_kmh(self) -> float:
        """Cruise velocity for time estimation (NOT energy)."""
        return CRUISE_VELOCITY_KMH

    @property
    def eco_velocity_kmh(self) -> float:
        """Eco velocity for energy computation — maximizes range."""
        return BASE_VELOCITY_KMH

    @property
    def consumption_multiplier(self) -> float:
        """Energy consumption scaling — always 1.0 (eco speed)."""
        return 1.0  # energy always at eco speed

    # ── Validation ──

    def __post_init__(self):
        # Allow passing a single destination string for convenience
        if isinstance(self.destinations, str):
            self.destinations = [self.destinations]

        if not self.destinations:
            raise ValueError("destinations must have at least one entry")

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
