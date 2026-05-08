# EV Route Planner

A personalized EV route planner that balances travel time, charging costs, and range anxiety using an Evolutionary Algorithm.

## Features
- **Real Vehicle Data**: Uses real EV specifications from ev-database.org (battery capacity, efficiency, range) via the `--car` flag.
- **Multi-destination Routing**: Plan complex journeys across multiple waypoints (e.g. Izmir -> Balikesir -> Eskisehir -> Ankara -> Istanbul). The journey is broken down into sequential legs.
- **Spend-Based Costing**: Cost is calculated from total energy *consumed* driving, not energy *charged*. If you start at 100% and end at 25% after charging once, the cost reflects 100% of energy spent.
- **Personalized Weights**: Prioritize time, cost, and range anxiety independently (1-5 scale).
- **Z-Score Optimization**: The Evolutionary Algorithm evaluates feasible routes and ranks them by a custom objective function (Z-score).
- **Visualization**: Generates route maps and Z-score convergence plots for the entire journey and leg-by-leg.

## Usage

The application is run via the CLI using `planner.main`.

### Single Destination Example
To find the best route from Izmir to Ankara using a Tesla Model 3 RWD (car ID 3403):

```powershell
python -m planner.main --car 3403 --source "Izmir, Turkey" --destinations "Ankara, Turkey" --battery-start 85 --battery-end 20 --w-time 3 --w-cost 3 --w-anxiety 3 -o output/izmir_ankara_run.txt
```

### Multi-Destination Example
To plan a multi-leg journey with a BMW iX3 (car ID 3290), prioritizing time:

```powershell
python -m planner.main --car 3290 --source "Izmir, Turkey" --destinations "Balikesir, Turkey" "Eskisehir, Turkey" "Ankara, Turkey" "Istanbul, Turkey" --battery-start 85 --battery-end 20 --w-time 5 --w-cost 3 --w-anxiety 2
```

## Velocity and Energy Model

Energy and time are decoupled for physical accuracy:

- **Energy**: Always computed at eco speed (70 km/h) to maximize range and ensure route feasibility.
- **Time**: Computed at cruise speed (90 km/h) or from real-world TomTom data.
- **Vehicle Specs**: Battery capacity and efficiency come from the ev-database.org JSON (`--car` flag).
- **Cost**: Total energy consumed driving × flat rate (TL per %).

*Note: Weather penalties apply to time only (not energy).*

## Project Structure
```
planner/
├── __init__.py          # Exported API symbols
├── main.py              # CLI entry point
├── pipeline.py          # Multi-leg orchestrator and ALNS framework
├── README.md            # This documentation
└── setup/               # Core domain logic
    ├── __init__.py
    ├── config.py        # Model configurations and velocity constants
    ├── ea_solver.py     # Evolutionary Algorithm
    ├── ev_vehicle.py    # EV database loader (ev-database.org JSON)
    ├── matrices.py      # Numpy cost/time/energy matrices
    ├── models.py        # Object data models (LegResult, RouteResult)
    ├── stations.py      # EPDK data loading and filtering
    ├── tomtom.py        # TomTom Geocoding & Routing APIs
    └── visualization.py # Matplotlib plotting functions
```
