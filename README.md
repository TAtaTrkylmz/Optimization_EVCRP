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
4.  **Dynamic Eco-Fallback**: Vehicle velocity (up to 140 km/h) is adjusted per segment. If a high speed is physically impossible for a specific leg between chargers, the system auto-falls back to "Eco-speed" (70 km/h).
5.  **Multi-Leg ALNS**: For trips with multiple destinations, an **Adaptive Large Neighborhood Search (ALNS)** inspired orchestrator manages battery "handoffs" between cities to optimize the global journey efficiency.

## 📂 Repository Structure

- `planner/`: The core Python package.
  - `main.py`: CLI entry point.
  - `pipeline.py`: Orchestrates multi-leg journeys and ALNS.
  - `setup/`: Computational engine (EA solver, math model, TomTom API).
- `data/`: Real Geocoded EPDK charging station database.
- `output/`: Generated maps and convergence plots.
- `doc/`: Mathematical model formulations and technical background.
- `requirements.txt`: Project dependencies.

## 📧 Requirements
- Python 3.10+
- TomTom API Key (configured in `.env`)
