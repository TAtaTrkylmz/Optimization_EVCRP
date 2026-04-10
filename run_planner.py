#!/usr/bin/env python
"""
CLI for the personalizable EV Route Planner.

Example (single line for PowerShell):
    python run_planner.py --source "Izmir, Turkey" --dest "Ankara, Turkey" --battery-start 85 --battery-end 20 --w-time 5 --w-cost 3 --w-anxiety 2
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from planner import EVRoutePlanner, UserPreferences
from planner.visualization import plot_route, plot_zscore_convergence


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Personalizable EV Route Planner (Evolutionary Algorithm)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Priorities are integers 1-5 (1 = least, 5 = most). Divided by 5 for weights.",
    )
    p.add_argument("--source", required=True, help='Source, e.g. "Izmir, Turkey"')
    p.add_argument("--dest", required=True, help='Destination, e.g. "Ankara, Turkey"')
    p.add_argument("--battery-start", type=float, required=True, help="Current battery %%")
    p.add_argument("--battery-end", type=float, required=True, help="Desired ending battery %%")
    p.add_argument("--battery-kwh", type=float, default=60.0, help="Battery capacity kWh (default: 60)")
    p.add_argument("--consumption", type=float, default=18.0, help="kWh/100km (default: 18)")
    p.add_argument("--w-time", type=int, default=3, choices=range(1, 6), metavar="1-5",
                   help="Time priority 1-5 (default: 3)")
    p.add_argument("--w-cost", type=int, default=3, choices=range(1, 6), metavar="1-5",
                   help="Cost priority 1-5 (default: 3)")
    p.add_argument("--w-anxiety", type=int, default=3, choices=range(1, 6), metavar="1-5",
                   help="Range anxiety priority 1-5 (default: 3)")
    p.add_argument("--battery-floor", type=float, default=0.0,
                   help="Never drop below this %% during travel (default: 0)")
    p.add_argument("--battery-ceil", type=float, default=100.0,
                   help="Never charge above this %% during travel (default: 100)")
    p.add_argument("-o", "--output", type=Path, default=None,
                   help="Write summary to a text file")
    return p


def format_route(result, prefs) -> str:
    """Pretty-print a single route result."""
    lines = [
        f"{'='*60}",
        f"  BEST ROUTE   (Z-score: {result.z_score:.2f})",
        f"{'='*60}",
        f"  Weights  ->  time={prefs.w_time:.1f}  cost={prefs.w_cost:.1f}  anxiety={prefs.w_anxiety:.1f}",
        f"  Enroute bounds  : floor={prefs.battery_min_enroute_pct:.0f}%  ceil={prefs.battery_max_enroute_pct:.0f}%",
        f"  Drive time      : {result.total_drive_time_min:.1f} min",
        f"  Charge time     : {result.total_charge_time_min:.1f} min",
        f"  Total time      : {result.total_time_min:.1f} min",
        f"  Total cost      : {result.total_cost:.1f} TL",
        f"  Battery at dest : {result.battery_at_destination_pct:.1f}%",
        "",
    ]
    if result.stops:
        lines.append("  Charging Stops:")
        for s in result.stops:
            lines.append(
                f"    * {s.station_name}  (ID {s.station_id}, {s.max_kw:.0f} kW)\n"
                f"      Arrive {s.battery_on_arrival_pct:.1f}% -> charge {s.charge_amount_pct:.1f}% "
                f"-> depart {s.battery_on_departure_pct:.1f}%  "
                f"({s.charge_time_min:.1f} min, {s.charge_cost:.1f} TL)"
            )
        lines.append("")
    else:
        lines.append("  No charging stops needed -- direct drive!\n")
    return "\n".join(lines)


def _make_save_name(prefs: UserPreferences) -> str:
    """Build filename: {src}_to_{dest}_{wt}-{wc}-{wa}"""
    src = prefs.source.replace(" ", "").replace(",", "")
    dst = prefs.destination.replace(" ", "").replace(",", "")
    return f"{src}_to_{dst}_{prefs.priority_time}-{prefs.priority_cost}-{prefs.priority_anxiety}"


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
        battery_min_enroute_pct=args.battery_floor,
        battery_max_enroute_pct=args.battery_ceil,
    )

    print()
    print("=" * 60)
    print("  EV ROUTE PLANNER")
    print("=" * 60)
    print(f"  From : {prefs.source}")
    print(f"  To   : {prefs.destination}")
    print(f"  Battery: {prefs.battery_start_pct:.0f}% now -> want {prefs.battery_end_min_pct:.0f}% at dest")
    print(f"  Enroute: floor={prefs.battery_min_enroute_pct:.0f}%  ceil={prefs.battery_max_enroute_pct:.0f}%")
    print(f"  Vehicle: {prefs.battery_capacity_kwh} kWh, {prefs.consumption_kwh_per_100km} kWh/100km")
    print(f"  Priorities (1-5): time={prefs.priority_time}  cost={prefs.priority_cost}  anxiety={prefs.priority_anxiety}")
    print(f"  Weights (0-1)   : time={prefs.w_time:.1f}  cost={prefs.w_cost:.1f}  anxiety={prefs.w_anxiety:.1f}")
    print("=" * 60)
    print()

    planner = EVRoutePlanner(prefs)
    best_route, all_evaluated, convergence = planner.plan_route()

    # Print best route details
    text = format_route(best_route, prefs)
    print(text)

    # Save text output if requested
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
        print(f"Results written to: {args.output.resolve()}")

    # Save route plot as {src}->{dest}_{wt}-{wc}-{wa}.png
    save_name = _make_save_name(prefs)
    save_dir = Path("output")
    save_dir.mkdir(parents=True, exist_ok=True)
    route_save = save_dir / f"{save_name}.png"

    plot_route(
        best_route, prefs,
        planner.coords, planner.station_meta,
        planner.dist_mat, planner.road_factor,
        save_path=route_save,
    )

    # Show Z-score convergence
    plot_zscore_convergence(convergence, prefs.source, prefs.destination)


if __name__ == "__main__":
    main()
