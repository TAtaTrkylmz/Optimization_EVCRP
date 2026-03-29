# Optimization_EVCRP

EV charging route / optimization work (MILP tests, route evaluation, EPDK geocoding scripts).

## Setup

**[SETUP.md](SETUP.md)** — create a `.venv`, install pinned dependencies from `requirements.txt`, and verify imports. Use this so everyone gets the same Python packages on macOS, Windows, or Linux.

## Geocoding

**[GEOCODING.md](GEOCODING.md)** — how `epdk_data.csv` is geocoded (Nominatim, Google, TomTom) and how `geocoded_epdk_data_partial.csv` / export splits work.

## Requirements

- Python 3.10+
- See `requirements.txt` (installed inside a virtual environment, not globally).
