#!/usr/bin/env python
"""
CLI for the personalizable EV Route Planner.

Example:
    python run_planner.py --source "Izmir, Turkey" --dest "Ankara, Turkey" \
        --battery-start 85 --battery-end 20 \
        --w-time 5 --w-cost 3 --w-anxiety 2
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure repo root is on sys.path so `milp` package imports work
REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from milp.ev_route_planner import EVRoutePlanner, UserPreferences, format_route


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Personalizable EV Route Planner — NumPy DP optimiser",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Priorities are integers 1-5 (1 = least important, 5 = most).\n"
            "They are converted to 0-1 floats by dividing by 5."
        ),
    )
    p.add_argument("--source", required=True, help='Source location, e.g. "Izmir, Turkey"')
    p.add_argument("--dest", required=True, help='Destination location, e.g. "Ankara, Turkey"')
    p.add_argument("--battery-start", type=float, required=True, help="Current battery level (%%)")
    p.add_argument("--battery-end", type=float, required=True, help="Desired ending battery level (%%)")
    p.add_argument("--battery-kwh", type=float, default=60.0, help="Battery capacity in kWh (default: 60)")
    p.add_argument("--consumption", type=float, default=18.0, help="Consumption in kWh/100km (default: 18)")
    p.add_argument("--w-time", type=int, default=3, choices=range(1, 6), metavar="1-5",
                   help="Time priority 1-5 (default: 3)")
    p.add_argument("--w-cost", type=int, default=3, choices=range(1, 6), metavar="1-5",
                   help="Cost priority 1-5 (default: 3)")
    p.add_argument("--w-anxiety", type=int, default=3, choices=range(1, 6), metavar="1-5",
                   help="Range anxiety priority 1-5 (default: 3)")
    p.add_argument("-o", "--output", type=Path, default=None,
                   help="Write results to a text file")
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    prefs = UserPreferences(
        source=args.source,
        destination=args.dest,
        battery_start_pct=args.battery_start,
        battery_end_min_pct=args.battery_end,
        battery_capacity_kwh=args.battery_kwh,
        consumption_kwh_per_100km=args.consumption,
        priority_time=args.w_time,
        priority_cost=args.w_cost,
        priority_anxiety=args.w_anxiety,
    )

    print()
    print("=" * 60)
    print("  EV ROUTE PLANNER")
    print("=" * 60)
    print(f"  From : {prefs.source}")
    print(f"  To   : {prefs.destination}")
    print(f"  Battery: {prefs.battery_start_pct:.0f}% now -> want {prefs.battery_end_min_pct:.0f}% at dest")
    print(f"  Vehicle: {prefs.battery_capacity_kwh} kWh, {prefs.consumption_kwh_per_100km} kWh/100km")
    print(f"  Priorities (1-5): time={prefs.priority_time}  cost={prefs.priority_cost}  anxiety={prefs.priority_anxiety}")
    print(f"  Weights (0-1)   : time={prefs.w_time:.1f}  cost={prefs.w_cost:.1f}  anxiety={prefs.w_anxiety:.1f}")
    print("=" * 60)
    print()

    planner = EVRoutePlanner(prefs)
    results = planner.plan_route()

    if not results:
        print("No feasible route found. Try increasing battery or relaxing end-battery target.")
        sys.exit(1)

    output_lines = []
    for r in results:
        text = format_route(r, prefs)
        print(text)
        output_lines.append(text)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text("\n".join(output_lines) + "\n", encoding="utf-8")
        print(f"Results written to: {args.output.resolve()}")


if __name__ == "__main__":
    main()
