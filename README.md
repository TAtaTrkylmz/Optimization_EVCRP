# Personalized EV Route Planner 🚗⚡

An advanced multi-destination route optimizer for Electric Vehicles. It uses **Evolutionary Computing** and a **Dynamic Drag Model** to balance travel time, charging costs, and range anxiety based on user preferences.

## 🚀 Quick Start

Run the planner from the repository root:

```bash
python -m planner.main --source "Izmir, Turkey" --destinations "Ankara, Turkey" "Istanbul, Turkey" --battery-start 85 --battery-end 20
```

## 🛠 Project Mechanism

The planner doesn't just find the shortest path; it evolves an optimal **charging strategy** using **Real Data** and a robust **Mathematical Model**.

1.  **Selection & Real Data (EPDK)**: The system utilizes official **EPDK (Energy Market Regulatory Authority of Turkey)** data—over 14,000 real charging sockets. It ignores "mock" values using actual TomTom API road coordinates.
2.  **Simulation & Math Model**: Each route is a candidate solution to a Mixed-Integer optimization problem. It minimizes a **Z-score**:
    - **Time**: $(T_{drive} + T_{charge}) \cdot Weight$
    - **Cost**: Total TL cost $\cdot$ Weight
    - **Anxiety**: Low battery penalty below 20% $\cdot$ Weight
3.  **Iteration (Evolution)**: Over 100 generations, routes "recombine" and "mutate." The solver handles complex constraints like $B_{floor} \le Battery \le B_{ceil}$ across thousands of station permutations.
4.  **Evolvable Segment Velocity**: Vehicle velocity factor ($s \in [0.7, 1.3]$) is evolved as a DNA gene per segment. Consumption is scaled using an aerodynamic drag model $E = E_{\text{eco}} \cdot s^{1.6}$, and speeds are capped using TomTom speed limits ($s_{\text{max}} = \min(1.3, v_{\text{TomTom}} \cdot 1.10 / 70)$) to prevent unrealistic speeds, naturally slowing down on city roads and speeding up on highways.
5.  **Multi-Leg ALNS**: For trips with multiple destinations, an **Adaptive Large Neighborhood Search (ALNS)** inspired orchestrator manages battery "handoffs" between cities to optimize the global journey efficiency.

## 🌍 Real-World Road Database (Offline Cache)

The planner natively supports calculating routes using exact real-world driving distances/times rather than straight-line estimates.
Because looking up thousands of road edges in real-time is extremely slow (and hits API quotas), the system uses an **Offline SQLite Database Cache** (`data/route_cache.db`).

### How to use cached roads:
1. **Pre-fetch a corridor:** Use the provided data fetcher tool to pre-fill the database for your journey. It will systematically query and cache the real road network along your path:
   ```bash
   python api/fetch_road_data.py --source "Konak, Izmir, Turkey" --destinations "Bornova, Izmir, Turkey" "Manisa"
   ```
2. **Run the planner:** Just run the planner normally! It will **automatically and silently** pull exact roads from the DB (under 0.1s processing time) and smoothly fall back to Haversine physics approximations for any edges not present in the DB. The CLI output will now explicitly report exactly how many edges were loaded from your Cache!
   *(Note: Avoid using `--live-traffic` unless specifically needed for real-time congestion analysis, as it will bypass the fast cache and fetch thousands of pairs individually, which can cause significant execution delays and API limit crashes).*

## 🔎 EV Database Scraper

To scrape EV models from EV Database with your custom filters (and manually solve CAPTCHA when needed), use:

```bash
python api/scrape_ev_database.py --url "https://ev-database.org/#group=vehicle-group&rs-pr=10000_100000&rs-er=0_1000&rs-ld=0_1000&rs-ac=2_23&rs-dcfc=0_400&rs-ub=10_200&rs-tw=0_3000&rs-ef=100_350&rs-sa=-1_5&rs-w=1000_3500&rs-c=0_5000&rs-y=2010_2030&s=1&p=0-50"
```

Pagination note: EV Database uses `p=pageIndex-pageSize` (e.g. `0-50`, `1-50`, `2-50`), not offset ranges.

The script runs a visible browser, pauses for manual CAPTCHA solve when detected, paginates through listing pages, and writes:

- `data/ev_database_vehicles.json`
- `data/ev_database_vehicles.csv`

Prerequisite (one-time):

```bash
pip install playwright
python -m playwright install chromium
```

For full detail pages from scratch (writes to separate files):

```bash
python api/scrape_ev_database_details.py --url "https://ev-database.org/#group=vehicle-group&rs-pr=10000_100000&rs-er=0_1000&rs-ld=0_1000&rs-ac=2_23&rs-dcfc=0_400&rs-ub=10_200&rs-tw=0_3000&rs-ef=100_350&rs-sa=-1_5&rs-w=1000_3500&rs-c=0_5000&rs-y=2010_2030&s=1&p=0-50" --max-pages 27
```

This generates:

- `data/ev_database_car_links.json`
- `data/ev_database_car_details.json`
- `data/ev_database_car_details.csv`

## 📂 Repository Structure

- `planner/`: The core Python package.
  - `main.py`: CLI entry point.
  - `pipeline.py`: Orchestrates multi-leg journeys and ALNS.
  - `setup/`: Computational engine (EA solver, math model, TomTom API).
- `web/`: Streamlit web app (jury demo UI).
  - `app.py`: Main Streamlit entry point.
  - `style.css`: Mobile-first custom CSS.
  - `.streamlit/config.toml`: Theme and server configuration.
- `data/`: Real Geocoded EPDK charging station database.
- `output/`: Generated maps and convergence plots.
- `doc/`: Mathematical model formulations and technical background.
- `requirements.txt`: Project dependencies.

## 📧 Requirements
- Python 3.10+
- TomTom API Key (configured in `.env`)

## 🌐 Web App (Streamlit — Jury Demo)

A mobile-first web interface for the route planner. The jury can access it by scanning a QR code on their smartphones.

### Setup

1. **Install dependencies** (from the repository root):
   ```bash
   pip install -r requirements.txt
   ```

2. **Allow network access through Windows Firewall** (one-time, required for phone access):
   ```powershell
   netsh advfirewall firewall add rule name="Streamlit" dir=in action=allow protocol=TCP localport=8501
   ```

3. **Launch the app**:
   ```bash
   streamlit run web/app.py
   ```
   The app binds to `0.0.0.0:8501` so any device on the same Wi-Fi network can connect.

### Jury Access via QR Code

1. Open the sidebar (hamburger menu on mobile, or click `>` on desktop).
2. A QR code and URL (e.g. `http://192.168.1.42:8501`) are displayed.
3. The jury scans the QR code with their phone camera → the app opens in their browser.
4. **Both the presenter's laptop and the jury's phones must be on the same Wi-Fi network.**

### Verification

After launching, verify the app is working:

```bash
# Check health endpoint
curl http://localhost:8501/_stcore/health
# Expected output: "ok"
```

To test the pipeline integration independently:

```bash
python -c "
import matplotlib; matplotlib.use('Agg')
import sys; sys.path.insert(0, '.')
from planner.setup.ev_vehicle import find_vehicle_by_id
from planner.setup.config import UserPreferences
from planner.pipeline import plan_journey
v = find_vehicle_by_id(3403)
prefs = UserPreferences(source='Izmir, Turkey', destinations=['Ankara, Turkey'],
    battery_start_pct=85, battery_end_min_pct=20,
    battery_capacity_kwh=v.battery_kwh,
    consumption_kwh_per_100km=v.consumption_kwh_per_100km,
    range_km=v.range_km)
r = plan_journey(prefs)
print(f'OK: {r.itinerary}, Z={r.total_z_score:.2f}')
"
```
