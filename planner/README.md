# EV Route Planner

A personalized EV route planner that balances travel time, charging costs, and range anxiety using an Evolutionary Algorithm.

## Features
- **Multi-destination Routing**: Plan complex journeys across multiple waypoints (e.g. Izmir -> Balikesir -> Eskisehir -> Ankara -> Istanbul). The journey is broken down into sequential legs.
- **Velocity Dynamics**: Faster driving (controlled by the `w-time` priority) increases energy consumption based on a quadratic drag model: `consumption = base_consumption * (velocity / base_velocity)^1.6`.
- **Personalized Weights**: Prioritize time, cost, and range anxiety independently (1-5 scale).
- **Z-Score Optimization**: The Evolutionary Algorithm evaluates feasible routes and ranks them by a custom objective function (Z-score).
- **Visualization**: Generates route maps and Z-score convergence plots for the entire journey and leg-by-leg.

## Usage

The application is run via the CLI using `planner.main`.

### Single Destination Example
To find the best route from Izmir to Ankara for a driver who balances all priorities equally (`w-time=3`), saving the text output to a file:

```powershell
python -m planner.main --source "Izmir, Turkey" --destinations "Ankara, Turkey" --battery-start 85 --battery-end 20 --w-time 3 --w-cost 3 --w-anxiety 3 -o output/izmir_ankara_run.txt
```

### Multi-Destination Example
To plan a multi-leg journey for a driver who values time above all else (`w-time=5` driving fast), resulting in higher energy consumption:

```powershell
python -m planner.main --source "Izmir, Turkey" --destinations "Balikesir, Turkey" "Eskisehir, Turkey" "Ankara, Turkey" "Istanbul, Turkey" --battery-start 85 --battery-end 20 --w-time 5 --w-cost 3 --w-anxiety 2
```

## Velocity and Consumption Data Flow
The route planner considers driver behavior when calculating routes:

1. **Preference Mapping**: `w-time` (1-5) maps to a target velocity (70 - 140 km/h).
2. **Multiplier Calculation**: The consumption multiplier is calculated as `(velocity_kmh / 70.0)^1.6`.
3. **Matrix Scaling**: The baseline EV consumption (`--consumption`, defaults to 18.0 kWh/100km) is multiplied by the consumption multiplier to create an adjusted energy matrix.
4. **Leg Planning**: Each leg independently evaluates path and charging constraints using this velocity-adjusted energy matrix.

For example:
- `w-time=1` -> Velocity: 70 km/h -> Multiplier: `(70/70)^1.6 = 1.00x`
- `w-time=3` -> Velocity: 105 km/h -> Multiplier: `(105/70)^1.6 ≈ 1.93x`
- `w-time=5` -> Velocity: 140 km/h -> Multiplier: `(140/70)^1.6 ≈ 3.03x`

*Note: In the future, this straight-line velocity scalar will be replaced by per-segment, road-specific speed limits.*

## Project Structure
```
planner/
├── __init__.py          # Exported API symbols
├── main.py              # CLI entry point
├── pipeline.py          # Multi-leg orchestrator and ALNS framework
├── README.md            # This documentation
└── setup/               # Core domain logic
    ├── __init__.py
    ├── config.py        # Model configurations and Velocity mappings
    ├── ea_solver.py     # Evolutionary Algorithm
    ├── matrices.py      # Numpy cost/time/energy matrices
    ├── models.py        # Object data models (LegResult, RouteResult)
    ├── stations.py      # EPDK data loading and filtering
    ├── tomtom.py        # TomTom Geocoding & Routing APIs
    └── visualization.py # Matplotlib plotting functions
```
