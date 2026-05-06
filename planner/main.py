#!/usr/bin/env python
"""
CLI entry point for the Personalizable EV Route Planner.

Example runs:

  Single destination:
    python -m planner.main --source "Izmir, Turkey" --destinations "Ankara, Turkey" \
        --battery-start 85 --battery-end 20 --w-time 3 --w-cost 3 --w-anxiety 3

  Multi-destination (ordered):
    python -m planner.main --source "Izmir, Turkey" \
        --destinations "Balikesir, Turkey" "Eskisehir, Turkey" "Ankara, Turkey" "Istanbul, Turkey" \
        --battery-start 85 --battery-end 20 --w-time 5 --w-cost 3 --w-anxiety 2

DESIGN: Weights only PRIORITIZE — they never control physics.
    --w-time    -> Z-score weight only (how much you care about time)
    --w-cost    -> Z-score weight only (how much you care about cost)
    --w-anxiety -> Z-score weight only (how much you care about range anxiety)
    Velocity is a fixed vehicle constant (90 km/h), not user-controllable.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from planner.setup.config import UserPreferences
from planner.pipeline import plan_journey
from planner.setup.visualization import show_all_plots
from api.mocker import set_occupancy_seed


# ---------------------------------------------------------------------------
# CLI argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Personalizable EV Route Planner (Evolutionary Algorithm)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Priorities are integers 1-5 (1 = least, 5 = most).\n"
            "They ONLY affect the Z-score ranking (which route is 'best').\n"
            "They do NOT change driving speed, energy consumption, or feasibility.\n"
            "Velocity is a fixed vehicle constant (90 km/h)."
        ),
    )
    p.add_argument("--source", required=True,
                   help='Starting point, e.g. "Izmir, Turkey"')
    p.add_argument("--destinations", required=True, nargs="+",
                   help='Ordered destination list, e.g. "Balikesir" "Ankara" "Istanbul"')
    p.add_argument("--battery-start", type=float, required=True,
                   help="Current battery %%")
    p.add_argument("--battery-end", type=float, required=True,
                   help="Desired ending battery %% at final destination")
    p.add_argument("--battery-kwh", type=float, default=60.0,
                   help="Battery capacity kWh (default: 60)")
    p.add_argument("--consumption", type=float, default=18.0,
                   help="Base kWh/100km at 70 km/h (default: 18)")
    p.add_argument("--w-time", type=int, default=3, choices=range(1, 6),
                   metavar="1-5",
                   help="Time priority 1-5 (default: 3)")
    p.add_argument("--w-cost", type=int, default=3, choices=range(1, 6),
                   metavar="1-5",
                   help="Cost priority 1-5 (default: 3)")
    p.add_argument("--w-anxiety", type=int, default=3, choices=range(1, 6),
                   metavar="1-5",
                   help="Range anxiety priority 1-5 (default: 3)")
    p.add_argument("--battery-floor", type=float, default=0.0,
                   help="Never drop below this %% during travel (default: 0)")
    p.add_argument("--battery-ceil", type=float, default=100.0,
                   help="Never charge above this %% during travel (default: 100)")
    p.add_argument("--weather-seed", type=int, default=42,
                   help="Random seed for mock weather generation (default: 42). "
                        "Use the same seed to reproduce experiments.")
    p.add_argument("--occupancy-seed", type=int, default=0,
                   help="Seed offset for station occupancy randomization (default: 0).")
    p.add_argument("--live-traffic", action="store_true",
                   help="Fetch real-world live traffic when planning routes (slower, hits API limits).")
    p.add_argument("-o", "--output", type=Path, default=None,
                   help="Write summary to a text file")
    return p


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def _format_leg(leg, leg_idx, total_legs) -> str:
    """Pretty-print a single leg result."""
    r = leg.route
    lines = [
        f"{'-'*50}",
        f"  LEG {leg_idx+1}/{total_legs}:  {leg.origin} -> {leg.destination}",
        f"  Z-score       : {r.z_score:.2f}",
        f"  Drive time    : {r.total_drive_time_min:.1f} min",
        f"  Charge time   : {r.total_charge_time_min:.1f} min",
        f"  Total time    : {r.total_time_min:.1f} min",
        f"  Total cost    : {r.total_cost:.1f} TL",
        f"  Battery at end: {r.battery_at_destination_pct:.1f}%",
        f"  Valid Routes  : {leg.feasible_routes_found} attempted paths evaluated",
        "",
    ]
    if r.stops:
        lines.append("  Charging Stops:")
        for s in r.stops:
            lines.append(
                f"    * {s.station_name}  (ID {s.station_id}, {s.max_kw:.0f} kW)\n"
                f"      Arrive {s.battery_on_arrival_pct:.1f}%"
                f" -> charge {s.charge_amount_pct:.1f}%"
                f" -> depart {s.battery_on_departure_pct:.1f}%  "
                f"({s.charge_time_min:.1f} min, {s.charge_cost:.1f} TL)"
            )
        lines.append("")
    else:
        lines.append("  No charging stops needed — direct drive!\n")
    return "\n".join(lines)


def _build_save_name(prefs) -> str:
    """Build a filename slug from itinerary and weights."""
    src = prefs.source.replace(" ", "").replace(",", "")
    dst = prefs.final_destination.replace(" ", "").replace(",", "")
    return (f"{src}_to_{dst}"
            f"_w{prefs.priority_time}-{prefs.priority_cost}-{prefs.priority_anxiety}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    prefs = UserPreferences(
        source=args.source,
        destinations=args.destinations,
        battery_start_pct=args.battery_start,
        battery_end_min_pct=args.battery_end,
        battery_capacity_kwh=args.battery_kwh,
        consumption_kwh_per_100km=args.consumption,
        priority_time=args.w_time,
        priority_cost=args.w_cost,
        priority_anxiety=args.w_anxiety,
        battery_min_enroute_pct=args.battery_floor,
        battery_max_enroute_pct=args.battery_ceil,
    )

    # Set occupancy seed for reproducibility
    set_occupancy_seed(args.occupancy_seed)

    # Run the pipeline
    try:
        result = plan_journey(prefs, live_traffic=args.live_traffic,
                              weather_seed=args.weather_seed)
    except RuntimeError as e:
        print(f"\n[!] PLANNING FAILED:")
        print(f"    {e}")
        sys.exit(1)

    # Build per-leg details text blob
    text_parts = []
    for leg in result.legs:
        part = _format_leg(leg, leg.leg_index, len(result.legs))
        text_parts.append(part)
    
    full_text = "\n".join(text_parts)
    print(full_text, flush=True)

    # Save text output if requested
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(full_text + "\n", encoding="utf-8")
        print(f"Results written to: {args.output.resolve()}")

    # Save plots
    save_name = _build_save_name(prefs)
    save_dir = Path("output")
    save_dir.mkdir(parents=True, exist_ok=True)

    # Show all maps and plots (combined journey map + convergence)
    show_all_plots(result, save_dir=save_dir, save_name=save_name)


if __name__ == "__main__":
    main()
