"""
Mock data generator for the EV Route Planner.

Provides simulated external factors:
  - Station occupancy (wait times)
  - Weather conditions (random quality squares over Turkey)

Runnable as a standalone script to preview / reproduce weather data:
  python api/mocker.py                         # defaults (seed=42)
  python api/mocker.py --seed 123              # different seed
  python api/mocker.py --seed 42 --min-sq 3 --max-sq 8
"""
from __future__ import annotations

import argparse
import random
import sys


# ---------------------------------------------------------------------------
# Turkey geographic bounds (limited to Turkey for computational feasibility)
# ---------------------------------------------------------------------------

TURKEY_LAT_MIN = 35.5
TURKEY_LAT_MAX = 42.5
TURKEY_LON_MIN = 25.5
TURKEY_LON_MAX = 45.0


# ---------------------------------------------------------------------------
# Station occupancy mock
# ---------------------------------------------------------------------------

_OCCUPANCY_SEED_OFFSET: int = 0    # global offset for reproducibility


def set_occupancy_seed(seed: int) -> None:
    """Set the global seed offset for station occupancy mock.
    
    The occupancy for each station is determined by:
        hash(station_id) + time_bucket + seed_offset
    So the same seed_offset always produces the same occupancy pattern.
    """
    global _OCCUPANCY_SEED_OFFSET
    _OCCUPANCY_SEED_OFFSET = seed


def get_mock_station_occupancy(station_id: str, arrival_time_min: float) -> dict:
    """
    Mock data generator for charging station status.
    Provides mocked wait times based on a simulated occupancy level.
    Uses _OCCUPANCY_SEED_OFFSET for reproducibility across experiments.
    """
    # Seed based on station id to have some consistency, but optionally time dependent
    # In a real scenario, this would call an external API.
    # We use a mix of station_id hash and time of day (in 10 min buckets) to simulate time-varying occupancy
    bucket = int(arrival_time_min // 10)
    rng = random.Random(hash(station_id) + bucket + _OCCUPANCY_SEED_OFFSET)
    
    occupancy_rate = rng.uniform(0.0, 1.0)
    
    wait_time_min = 0.0
    if occupancy_rate > 0.8:
        # High occupancy, 5 to 20 minutes wait
        wait_time_min = rng.uniform(5.0, 20.0)
    elif occupancy_rate > 0.6:
        # Moderate occupancy, 0 to 10 minutes wait
        wait_time_min = rng.uniform(0.0, 10.0)
        
    return {
        "station_id": station_id,
        "occupancy_rate": occupancy_rate,
        "wait_time_min": round(wait_time_min, 1)
    }


# ---------------------------------------------------------------------------
# Weather mock — random quality squares over Turkey
# ---------------------------------------------------------------------------

class WeatherSquare:
    """A rectangular region with a weather quality grade."""
    __slots__ = ("lat_min", "lat_max", "lon_min", "lon_max", "quality")

    def __init__(self, lat_min: float, lat_max: float,
                 lon_min: float, lon_max: float, quality: float):
        self.lat_min = lat_min
        self.lat_max = lat_max
        self.lon_min = lon_min
        self.lon_max = lon_max
        self.quality = quality   # 0.0 = worst weather, 1.0 = clear (good weather)

    def contains(self, lat: float, lon: float) -> bool:
        """Check if a point falls inside this square."""
        return (self.lat_min <= lat <= self.lat_max and
                self.lon_min <= lon <= self.lon_max)

    def __repr__(self):
        return (f"WeatherSquare(lat=[{self.lat_min:.2f},{self.lat_max:.2f}], "
                f"lon=[{self.lon_min:.2f},{self.lon_max:.2f}], q={self.quality:.2f})")


def get_mock_weather(
    seed: int = 42,
    min_squares: int = 2,
    max_squares: int = 6,
) -> list[WeatherSquare]:
    """Generate random weather squares covering parts of Turkey.

    The bounds are fixed to Turkey's geographic extent:
        Latitude  : 35.5° – 42.5°
        Longitude : 25.5° – 45.0°

    Logic:
        1. Pick a random number of squares (between min_squares and max_squares).
        2. Each square has a random position and size within Turkey.
        3. Each square gets a weather quality grade between 0.2 and 0.8
           (never fully blocking, never fully clear).
        4. Regions NOT covered by any square are implicitly quality=1.0 (clear).

    The quality value is used as a time multiplier:
        effective_time = base_time / quality
        e.g. quality=0.5 means travel takes 2x longer through that region.

    Args:
        seed:         random seed for reproducibility (use same seed for experiments)
        min_squares:  minimum number of weather squares (>= 2)
        max_squares:  maximum number of weather squares

    Returns:
        List of WeatherSquare objects.
    """
    rng = random.Random(seed)
    min_squares = max(2, min_squares)   # enforce at least 2
    n_squares = rng.randint(min_squares, max(min_squares, max_squares))

    lat_span = TURKEY_LAT_MAX - TURKEY_LAT_MIN   # ~7°
    lon_span = TURKEY_LON_MAX - TURKEY_LON_MIN    # ~19.5°

    squares: list[WeatherSquare] = []
    for _ in range(n_squares):
        # Random size: 10% to 40% of Turkey's span
        sq_lat_size = rng.uniform(0.10, 0.40) * lat_span
        sq_lon_size = rng.uniform(0.10, 0.40) * lon_span

        # Random position (anchor is bottom-left corner)
        sq_lat_min = rng.uniform(TURKEY_LAT_MIN, TURKEY_LAT_MAX - sq_lat_size)
        sq_lon_min = rng.uniform(TURKEY_LON_MIN, TURKEY_LON_MAX - sq_lon_size)

        # Weather quality: 0.2 to 0.8 (never fully blocking, never fully clear)
        quality = round(rng.uniform(0.4, 0.8), 2)

        squares.append(WeatherSquare(
            lat_min=round(sq_lat_min, 4),
            lat_max=round(sq_lat_min + sq_lat_size, 4),
            lon_min=round(sq_lon_min, 4),
            lon_max=round(sq_lon_min + sq_lon_size, 4),
            quality=quality,
        ))

    return squares


def get_weather_penalty(lat: float, lon: float,
                        squares: list[WeatherSquare]) -> float:
    """Get the weather time-multiplier for a specific point.

    If the point falls inside one or more weather squares, we take
    the WORST (lowest) quality and return 1/quality as the multiplier.
    If outside all squares, returns 1.0 (no penalty).

    Returns:
        float >= 1.0  (time multiplier)
    """
    worst_quality = 1.0
    for sq in squares:
        if sq.contains(lat, lon):
            worst_quality = min(worst_quality, sq.quality)
    return 1.0 / worst_quality if worst_quality > 0 else 5.0


def get_segment_weather_penalty(
    lat1: float, lon1: float,
    lat2: float, lon2: float,
    squares: list[WeatherSquare],
    n_samples: int = 5,
) -> float:
    """Get the average weather time-multiplier along a segment.

    Samples N points along the segment (including endpoints) and
    averages their penalties. This is more accurate than checking
    just the endpoints.

    Returns:
        float >= 1.0  (average time multiplier along the segment)
    """
    if not squares:
        return 1.0

    total = 0.0
    for k in range(n_samples):
        t = k / max(n_samples - 1, 1)
        lat = lat1 + t * (lat2 - lat1)
        lon = lon1 + t * (lon2 - lon1)
        total += get_weather_penalty(lat, lon, squares)

    return total / n_samples


# ---------------------------------------------------------------------------
# CLI for standalone execution
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Mock Data Generator for the EV Route Planner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Generates random weather and station occupancy data.\n"
            "Use --seed to reproduce the exact same data for experiments.\n\n"
            "Examples:\n"
            "  python api/mocker.py                              # default seed=42\n"
            "  python api/mocker.py --seed 123                   # different scenario\n"
            "  python api/mocker.py --seed 42 --max-sq 8         # more weather zones\n"
            "  python api/mocker.py --seed 42 --occupancy-seed 7 # custom occupancy\n"
        ),
    )
    p.add_argument("--seed", type=int, default=42,
                   help="Random seed for weather reproducibility (default: 42)")
    p.add_argument("--min-sq", type=int, default=2,
                   help="Minimum number of weather squares (default: 2)")
    p.add_argument("--max-sq", type=int, default=6,
                   help="Maximum number of weather squares (default: 6)")
    p.add_argument("--occupancy-seed", type=int, default=0,
                   help="Seed offset for station occupancy randomization (default: 0)")
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    # Set occupancy seed
    set_occupancy_seed(args.occupancy_seed)

    print(f"\n{'='*60}")
    print(f"  MOCK DATA GENERATOR")
    print(f"{'='*60}")
    print(f"  Weather seed   : {args.seed}")
    print(f"  Square range   : [{args.min_sq}, {args.max_sq}]")
    print(f"  Occupancy seed : {args.occupancy_seed}")
    print(f"  Bounds         : Turkey (lat {TURKEY_LAT_MIN}-{TURKEY_LAT_MAX}, "
          f"lon {TURKEY_LON_MIN}-{TURKEY_LON_MAX})")
    print(f"{'='*60}")

    # ── Weather ──
    squares = get_mock_weather(
        seed=args.seed,
        min_squares=args.min_sq,
        max_squares=args.max_sq,
    )

    print(f"\n  WEATHER: {len(squares)} zone(s)\n")
    for i, sq in enumerate(squares, 1):
        penalty = 1.0 / sq.quality
        print(f"  [{i}] {sq}")
        print(f"      Time penalty: x{penalty:.2f} (quality={sq.quality:.2f})")
        print()

    print(f"  {'-'*50}")
    print(f"  Sample weather penalties:")
    test_points = [
        ("Ankara", 39.93, 32.86),
        ("Istanbul", 41.01, 28.98),
        ("Izmir", 38.42, 27.14),
        ("Antalya", 36.90, 30.69),
    ]
    for name, lat, lon in test_points:
        penalty = get_weather_penalty(lat, lon, squares)
        status = f"x{penalty:.2f}" if penalty > 1.0 else "clear"
        print(f"    {name:12s} ({lat:.2f}, {lon:.2f}): {status}")

    # ── Station occupancy ──
    print(f"\n  {'-'*50}")
    print(f"  STATION OCCUPANCY (seed offset={args.occupancy_seed}):")
    print(f"  Sample stations at arrival_time=0 min:\n")
    sample_stations = [
        "STN-001", "STN-050", "STN-100", "STN-200", "STN-500",
    ]
    for sid in sample_stations:
        occ = get_mock_station_occupancy(sid, 0.0)
        occ_bar = '#' * int(occ['occupancy_rate'] * 20)
        print(f"    {sid}: occupancy={occ['occupancy_rate']:.2f} [{occ_bar:20s}] "
              f"wait={occ['wait_time_min']}min")

    print(f"\n  To reproduce: python api/mocker.py --seed {args.seed} "
          f"--min-sq {args.min_sq} --max-sq {args.max_sq} "
          f"--occupancy-seed {args.occupancy_seed}\n")


if __name__ == "__main__":
    main()
