# Izmir → Ankara real-data route test

This document describes **`milp/izmir_ankara_tomtom_epdk_test.py`**: an end-to-end scenario that combines TomTom APIs, the geocoded EPDK charging dataset, and the same EV routing MILP structure as `milp/MILP_solverfw_test.py`.

## What it does

1. **Geocode** origin and destination with TomTom Search (`Izmir, Turkey` → `Ankara, Turkey`, `countrySet=TR`).
2. **Route summary** with TomTom Routing (`calculateRoute`, `routeRepresentation=summaryOnly`): total road distance (km) and travel time (minutes).
3. **Load stations** from `data/geocoded_epdk_data.csv`, aggregate by **`İstasyon No`** (max **`Soket Gücü (kW)`**, first coordinates/name).
4. **Filter** to a corridor between origin and destination (cross-track distance and along-track window), then **subsample** to at most 40 stations so the MILP stays tractable.
5. **Build a forward-only graph** (origin → stations in order → destination). Leg distance and time are **scaled from haversine** using the ratio of TomTom road length to great-circle length (see limitations below).
6. **Solve** the MILP (PuLP + CBC): route choice, charge amounts, battery and linear anxiety penalty, weighted objective.

## Prerequisites

- Python environment with dependencies from `requirements.txt` (see **[SETUP.md](SETUP.md)**). From the repo root, the project **`venv/`** is typically used:

  ```bash
  source venv/bin/activate   # or: ./venv/bin/python …
  ```

- **`TOMTOM_API_KEY`** in the environment or in a repo-root **`.env`** file (same convention as `api/geocode_tomtom.py`). The key value must be a single token on its own line (no trailing comments or stray quotes on the same line).

- **`data/geocoded_epdk_data.csv`** present (geocoded EPDK export).

## How to run

Always run from the **repository root** so `data/` paths resolve.

```bash
./venv/bin/python milp/izmir_ankara_tomtom_epdk_test.py
```

### Command-line options

| Option | Description |
|--------|-------------|
| `-o PATH`, `--output PATH` | Where to write the report **`.txt`** file. Default: `output/izmir_ankara_last_run.txt`. |
| `--no-output-file` | Print only to stdout; do **not** create or overwrite a report file. |

Examples:

```bash
./venv/bin/python milp/izmir_ankara_tomtom_epdk_test.py -o output/run_2026-03-30.txt
./venv/bin/python milp/izmir_ankara_tomtom_epdk_test.py --no-output-file
```

The **`output/`** directory is created automatically if missing. It is listed in **`.gitignore`** so local run artifacts are not committed by default.

## Report file contents

The **`.txt`** file is the same text as stdout (plain UTF-8), including:

- UTC timestamp at the start of the run
- Geocoded coordinates and TomTom route summary
- Count of corridor stations and **snapshot of main model constants** (battery, weights, corridor caps)
- MILP status, objective value, chosen **drive legs**, and **charging** decisions

On failure (e.g. infeasible MILP or no edges from origin), a **partial** report may still be written when file output is enabled, with a footer noting that the file is partial.

## Tunable parameters

All are constants at the top of **`milp/izmir_ankara_tomtom_epdk_test.py`** (scenario queries, `B_MAX`, `THRESHOLD`, weights `W1/W2/W3`, `BATTERY_KWH`, `KWH_PER_100KM`, corridor width, `MAX_STATIONS_IN_MODEL`, charging cost placeholder, DC efficiency factor for time-per-%).

## Limitations (read before trusting numbers)

- **Leg geometry**: Drive time and energy on each arc are **not** from per-leg TomTom routes; they use **haversine** between nodes scaled to match **overall** TomTom distance/time. Detours and real road shape between intermediate chargers are not modeled.
- **Charging price** is a **placeholder** per percent of SOC; real tariffs are not in the CSV.
- **Traffic** and time-dependent routing are not applied unless you change the API parameters yourself.
- **Station cap** (40) can drop feasible real-world stops; increase with care (MILP size grows quickly).

For production-style accuracy, consider TomTom **matrix** or **multiple calculateRoute** calls per leg, or snapping stations to a route polyline.

## Related files

| File | Role |
|------|------|
| `milp/MILP_solverfw_test.py` | Small synthetic MILP (same constraint pattern) |
| `milp/RouteEvaluator.py` | Post-hoc Z-score with **quadratic** anxiety (not used by this script’s MILP) |
| `api/geocode_tomtom.py` | Batch TomTom geocoding for EPDK addresses |
| `doc/GEOCODING.md` | How `geocoded_epdk_data.csv` is produced |
