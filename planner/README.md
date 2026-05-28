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

Energy and time are optimized dynamically using per-segment velocity genes in the Evolutionary Algorithm:

- **Per-Segment Speed Gene**: The EA chromosome is structured as `[(station_node, charge_pct, speed_factor), ...]`. The `speed_factor` ($s$) is evolved dynamically for each segment in the range $[0.7, 1.3]$, scaling the vehicle speed $v = 70 \cdot s$ (km/h) between 49 km/h (highly eco) and 91 km/h (aggressive).
- **TomTom Speed Limits**: The speed factor for each edge is capped using the average real-world driving speed derived from cached TomTom data, plus 10% headroom:
  $$s_{\text{max}} = \min\left(1.3, \frac{v_{\text{TomTom}} \cdot 1.10}{70}\right)$$
- **Aerodynamic Drag Energy Scaling**: Energy consumption scales non-linearly with speed to model aerodynamic resistance, using a drag exponent of 1.6:
  $$E = E_{\text{eco}} \cdot s^{1.6}$$
  where $E_{\text{eco}}$ is the base energy consumption at the eco baseline speed of 70 km/h.
- **Travel Time Scaling**: Travel time scales inversely with the chosen speed factor relative to the baseline speed used to calculate the path:
  $$T = T_{\text{base}} \cdot \frac{v_{\text{default}}}{70 \cdot s}$$
  where $v_{\text{default}}$ is the baseline speed used to populate the cost matrix (cached TomTom average speed for cache hits, or cruise speed 90 km/h for fallback cache misses).
- **Weather Penalties**: Weather multiplier affects time only ($T_{\text{base}}$ is pre-multiplied by the weather penalty).

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
