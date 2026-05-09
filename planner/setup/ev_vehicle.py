"""
EV vehicle database loader.

Loads real vehicle specifications from data/ev_database_vehicles.json
and provides lookup by ev-database.org car ID.

Usage:
    from planner.setup.ev_vehicle import find_vehicle_by_id

    vehicle = find_vehicle_by_id(3403)
    print(vehicle)
    # EVVehicle(name='Tesla Model 3 RWD (Highland)', car_id=3403,
    #           battery_kwh=60.0, efficiency_wh_per_km=135.0, ...)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EV_DATABASE_JSON = REPO_ROOT / "data" / "ev_database_vehicles.json"


@dataclass
class EVVehicle:
    """Real-world EV specifications from ev-database.org."""
    name: str
    car_id: int
    battery_kwh: float
    efficiency_wh_per_km: float       # Wh/km (e.g. 135)
    range_km: float
    fastcharge_kw: float | None
    weight_kg: float
    href: str

    @property
    def consumption_kwh_per_100km(self) -> float:
        """Convert Wh/km to kWh/100km (e.g. 135 Wh/km → 13.5 kWh/100km)."""
        return self.efficiency_wh_per_km / 10.0


def _extract_car_id(href: str) -> int | None:
    """Extract numeric car ID from ev-database.org URL.

    Example: 'https://ev-database.org/car/3403/Tesla-Model-3-RWD' → 3403
    """
    m = re.search(r"/car/(\d+)/", href)
    return int(m.group(1)) if m else None


def load_ev_database() -> list[dict]:
    """Load the full EV database from the JSON file."""
    with open(EV_DATABASE_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


def find_vehicle_by_id(car_id: int) -> EVVehicle:
    """Look up a vehicle by its ev-database.org numeric ID.

    Args:
        car_id: The number from the URL, e.g. 3403

    Returns:
        EVVehicle with all specs populated.

    Raises:
        SystemExit: If the car ID is not found (prints suggestions).
    """
    db = load_ev_database()

    # Build index: car_id → entry
    index: dict[int, dict] = {}
    for entry in db:
        cid = _extract_car_id(entry.get("href", ""))
        if cid is not None:
            index[cid] = entry

    if car_id in index:
        entry = index[car_id]
        return _entry_to_vehicle(entry, car_id)

    # Not found — show closest matches
    log.warn(f"Car ID {car_id} not found in the EV database.")
    log.step(f"Database contains {len(index)} vehicles.")

    # Try to find partial name matches or close IDs
    close_ids = sorted(index.keys(), key=lambda x: abs(x - car_id))[:10]
    log.info("Closest car IDs:")
    for cid in close_ids:
        name = index[cid].get("name", "Unknown")
        log.step(f"--car {cid}  ->  {name}")

    raise SystemExit(1)


def _entry_to_vehicle(entry: dict, car_id: int) -> EVVehicle:
    """Convert a raw JSON entry to an EVVehicle dataclass."""
    return EVVehicle(
        name=_clean_name(entry.get("name", "Unknown")),
        car_id=car_id,
        battery_kwh=float(entry.get("battery_kwh", 0)),
        efficiency_wh_per_km=float(entry.get("efficiency_wh_per_km", 0)),
        range_km=float(entry.get("range_km", 0)),
        fastcharge_kw=entry.get("fastcharge_kw"),
        weight_kg=float(entry.get("weight_kg", 0)),
        href=entry.get("href", ""),
    )


def _clean_name(raw_name: str) -> str:
    """Clean up the vehicle name.

    The JSON 'name' field often has trailing status text like
    'Available', 'Discontinued (October 2021', etc.
    Strip those and keep only the model name.
    """
    # Remove common trailing patterns
    patterns = [
        r"\s+Available.*$",
        r"\s+Discontinued.*$",
        r"\s+to order.*$",
    ]
    name = raw_name.strip()
    for pat in patterns:
        name = re.sub(pat, "", name, flags=re.IGNORECASE)
    return name.strip()


from planner.setup.logger import log


def log_vehicle_banner(vehicle: EVVehicle) -> None:
    """Print a formatted vehicle banner at the start of logs."""
    fc = f"{vehicle.fastcharge_kw:.0f} kW DC" if vehicle.fastcharge_kw else "N/A"
    lines = [
        f"VEHICLE: {vehicle.name}",
        f"Battery      : {vehicle.battery_kwh:.1f} kWh",
        f"Efficiency   : {vehicle.efficiency_wh_per_km:.0f} Wh/km  ({vehicle.consumption_kwh_per_100km:.1f} kWh/100km)",
        f"Range        : {vehicle.range_km:.0f} km",
        f"Fast Charge  : {fc}",
        f"Weight       : {vehicle.weight_kg:.0f} kg",
        f"ev-database  : car/{vehicle.car_id}"
    ]
    log.banner(lines)
