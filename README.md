# Optimization_EVCRP

EV charging route / optimization work (MILP tests, route evaluation, EPDK geocoding scripts).

## Repository layout

| Directory | Contents |
|-----------|----------|
| `api/` | Geocoding scripts (Nominatim, Google, TomTom) and API smoke tests |
| `data/` | EPDK CSVs, geocoded outputs, checkpoints, intermediate extracts |
| `doc/` | Setup and geocoding documentation |
| `milp/` | MILP solver experiments, route evaluation, and **[Izmir→Ankara real-data test](doc/IZMIR_ANKARA_ROUTE_TEST.md)** (`izmir_ankara_tomtom_epdk_test.py`) |
| `util/` | Helpers: ungeocoded extract, split partial CSV into geocoded + missing |

Run Python entrypoints from the **repository root** so paths resolve to `data/` correctly (for example `python api/geocode_osm.py`).

## Setup

**[doc/SETUP.md](doc/SETUP.md)** — create a `.venv`, install pinned dependencies from `requirements.txt`, and verify imports. Use this so everyone gets the same Python packages on macOS, Windows, or Linux.

## Geocoding

**[doc/GEOCODING.md](doc/GEOCODING.md)** — how `data/epdk_data.csv` is geocoded (Nominatim, Google, TomTom) and how `data/geocoded_epdk_data_partial.csv` / export splits work.

## Izmir → Ankara scenario test

**[doc/IZMIR_ANKARA_ROUTE_TEST.md](doc/IZMIR_ANKARA_ROUTE_TEST.md)** — TomTom + `geocoded_epdk_data.csv` + MILP; writes `output/izmir_ankara_last_run.txt` by default.

## Requirements

- Python 3.10+
- See `requirements.txt` (installed inside a virtual environment, not globally).
