# Personalizable EV Route Planner

This tool provides a customizable EV route planning experience using real-world charging station data (EPDK) and TomTom APIs for routing and geocoding.

## Features

- **Personalizable Weights**: Adjust priorities for driving time, total cost, and range anxiety (1-5 scale).
- **Custom Battery Targets**: Specify current SOC (%) and desired SOC at arrival (%).
- **Vehicle Configuration**: Set battery capacity (kWh) and consumption (kWh/100km).
- **Top-3 Alternatives**: Automatically generates up to 3 alternative routes by strategically excluding intermediate charging stops.
- **Dynamic Programming (NumPy)**: Uses a fast forward DP algorithm instead of traditional MILP solvers.
- **Contextual Suggestions**: Receive suggestions for breaks and POIs nearby (mock data currently).

## Usage

Run `run_planner.py` from the repository root:

```bash
python run_planner.py \
  --source "Izmir, Turkey" \
  --dest "Ankara, Turkey" \
  --battery-start 85 \
  --battery-end 20 \
  --w-time 5 \
  --w-cost 3 \
  --w-anxiety 2
```

### Command Line Arguments

| Argument | Description | Default |
|---|---|---|
| `--source` | Origin address or city name | (Required) |
| `--dest` | Destination address or city name | (Required) |
| `--battery-start` | Current battery percentage (0-100) | (Required) |
| `--battery-end` | Minimum battery percentage on arrival (0-100) | (Required) |
| `--battery-kwh` | Battery capacity in kWh | 60.0 |
| `--consumption` | Consumption in kWh/100km | 18.0 |
| `--w-time` | Time priority (1-5, where 5 is high importace) | 3 |
| `--w-cost` | Cost priority (1-5) | 3 |
| `--w-anxiety` | Range anxiety priority (1-5) | 3 |
| `-o, --output` | Path to save the report as a .txt file | None |

## Optimization Engine

The planner builds a corridor-focused graph of charging stations between the origin and destination. It then uses a **forward dynamic programming (DP)** algorithm implemented in NumPy to find the optimal charging strategy.

Unlike the previous `milp/izmir_ankara_tomtom_epdk_test.py` which uses PuLP (Mixed Integer Linear Programming), this tool is optimized for speed and works on a discretized battery state space (5% steps).

## Data Sources

- **Geocoding & Routing**: [TomTom Search API](https://developer.tomtom.com/search-api) & [TomTom Routing API](https://developer.tomtom.com/routing-api).
- **Charging Stations**: `data/geocoded_epdk_data.csv` (contains location and socket power for stations across Turkey).

## Implementation Details

- **Core Module**: `milp/ev_route_planner.py` contains the `EVRoutePlanner` and `UserPreferences` classes.
- **Preferences**: Priorities are converted from 1-5 integers to 0.2-1.0 floats by dividing by 5.
- **Anxiety Penalty**: Penalty is triggered when SOC falls below **20%**.
- **Alternative Routes**: Strategic re-running of the optimizer by excluding stops found in the primary path.
