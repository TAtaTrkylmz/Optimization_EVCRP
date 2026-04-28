"""
Constants and user preferences for the EV route planner.

Velocity model:
    velocity_kmh = 70 + (priority_time - 1) * 17.5   ->  [70, 140] km/h
    consumption_multiplier = (velocity / 70) ^ 1.6
    At 70 km/h  -> 1.0x  (baseline)
    At 140 km/h -> ~3.03x (high-speed penalty)
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
BASE_VELOCITY_KMH = 70.0         # w_time=1  (slow, efficient)
MAX_VELOCITY_KMH = 140.0         # w_time=5  (fast, hungry)
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


# ── Helper: velocity from priority ──

def _velocity_from_priority(priority_time: int) -> float:
    """Map time priority (1-5) to velocity (70-140 km/h)."""
    step = (MAX_VELOCITY_KMH - BASE_VELOCITY_KMH) / 4.0   # 17.5 km/h per step
    return BASE_VELOCITY_KMH + (priority_time - 1) * step


def _consumption_multiplier(velocity_kmh: float) -> float:
    """Drag-based consumption scaling: (v / v_base) ^ 1.6."""
    return (velocity_kmh / BASE_VELOCITY_KMH) ** VELOCITY_EXPONENT


# ── User preferences ──

@dataclass
class UserPreferences:
    """All user-configurable inputs for the route planner.

    Priorities are integers 1-5, converted to 0-1 floats by dividing by 5.
    destinations is an ordered list — visited in the given sequence.
    Example: source="Izmir", destinations=["Balikesir", "Eskisehir", "Ankara", "Istanbul"]
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
        """Driving velocity based on time priority (70-140 km/h)."""
        return _velocity_from_priority(self.priority_time)

    @property
    def consumption_multiplier(self) -> float:
        """Energy consumption scaling from velocity: (v/v_base)^1.6."""
        return _consumption_multiplier(self.velocity_kmh)

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
