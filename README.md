# Optimization_EVCRP

EV charging route / optimization work (MILP tests, route evaluation, EPDK geocoding scripts).

## Repository layout

| Directory | Contents |
|-----------|----------|
| `api/` | Geocoding scripts (Nominatim, Google, TomTom) and API smoke tests |
| `data/` | EPDK CSVs, geocoded outputs, checkpoints, intermediate extracts |
| `doc/` | Setup and geocoding documentation |
| `milp/` | MILP/DP solver experiments, route evaluation, and **[Izmir→Ankara real-data test](doc/IZMIR_ANKARA_ROUTE_TEST.md)** (`izmir_ankara_tomtom_epdk_test.py`) |
| `util/` | Helpers: ungeocoded extract, split partial CSV into geocoded + missing |
| `run_planner.py` | **[Personalizable EV Route Planner](doc/PERSONALIZABLE_PLANNER.md)** — CLI for optimal routing with user preferences |

Run Python entrypoints from the **repository root** so paths resolve to `data/` correctly (for example `python run_planner.py --source "Izmir" --dest "Ankara" --battery-start 85 --battery-end 20`).

## Setup

**[doc/SETUP.md](doc/SETUP.md)** — create a `.venv`, install pinned dependencies from `requirements.txt`, and verify imports.

## Geocoding

**[doc/GEOCODING.md](doc/GEOCODING.md)** — how `data/epdk_data.csv` is geocoding process and outputs.

## Personalizable EV Route Planning

**[doc/PERSONALIZABLE_PLANNER.md](doc/PERSONALIZABLE_PLANNER.md)** — New NumPy-based dynamic programming planner with user-configurable priorities and battery targets.

```bash
python run_planner.py --source "Izmir, Turkey" --dest "Ankara, Turkey" --battery-start 85 --battery-end 20
```

## Izmir → Ankara MILP (Legacy)

**[doc/IZMIR_ANKARA_ROUTE_TEST.md](doc/IZMIR_ANKARA_ROUTE_TEST.md)** — TomTom + `geocoded_epdk_data.csv` + MILP solve using PuLP. (old)

## Requirements

- Python 3.10+
- See `requirements.txt` (installed inside a virtual environment).
