#!/usr/bin/env python
"""
Detailed benchmark runner for EV Route Planner.
Runs multiple vehicle models, priority profiles, weather seeds, and occupancy seeds
fully offline by patching TomTom APIs, then saves results and generates comparison graphs.
"""
import sys
import os
import time
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path

# Add repo root to path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# 1. Keep original TomTom functions (which are already cache-first)
import planner.setup.tomtom as tomtom

# No monkeypatching is needed for route_with_geometry, as the original function
# in planner.setup.tomtom already checks the cache and falls back to the TomTom API.
# We only patch geocode and route_summary for safety when cache is missed.

def mock_geocode(query, api_key):
    cached = tomtom.get_geocode_from_cache(query)
    if cached is not None:
        return cached
    # Fallback to cache or raise if missing during benchmark
    try:
        return tomtom.geocode(query, api_key)
    except Exception as e:
        q_lower = query.lower()
        if "izmir" in q_lower:
            return (38.418724, 27.129601)
        elif "ankara" in q_lower:
            return (39.8965202, 32.8619738)
        elif "trabzon" in q_lower:
            return (41.0020719, 39.7192164)
        raise e

def mock_route_summary(lat_o, lon_o, lat_d, lon_d, api_key, use_cache=True, live_traffic=False):
    cached = tomtom.get_route_from_cache(lat_o, lon_o, lat_d, lon_d)
    if cached is not None:
        return cached
    return tomtom.route_summary(lat_o, lon_o, lat_d, lon_d, api_key, use_cache, live_traffic)

# Apply geocode and route_summary patches
tomtom.geocode = mock_geocode
tomtom.route_summary = mock_route_summary

# 2. Disable default logs during benchmark to avoid cluttering stdout
from planner.setup.logger import log as logger
logger.info = lambda *args, **kwargs: None
logger.step = lambda *args, **kwargs: None
logger.warn = lambda *args, **kwargs: None
logger.banner = lambda *args, **kwargs: None
logger.section = lambda *args, **kwargs: None
logger.metric = lambda *args, **kwargs: None

from planner.setup.config import UserPreferences
from planner.setup.ev_vehicle import find_vehicle_by_id
from planner.pipeline import plan_journey

# Configuration
WAYPOINTS = ["Izmir, Turkey", "Ankara, Turkey", "Trabzon, Turkey"]
WAYPOINT_COORDS = [
    (38.418724, 27.129601),
    (39.8965202, 32.8619738),
    (41.0020719, 39.7192164)
]

CARS = {
    "Tesla Model 3 Highland": 3403,
    "Tesla Model Y Long Range": 3104,
    "MG MG4 Electric 64kWh": 1708,
    "Fiat 500e Hatchback 42kWh": 1285,
    "TOGG T10F Long Range": 3305
}

PROFILES = {
    "Scenario A (Time)": {"time": 5, "cost": 1, "anxiety": 1},
    "Scenario B (Cost)": {"time": 1, "cost": 5, "anxiety": 1},
    "Scenario C (Comfort)": {"time": 3, "cost": 2, "anxiety": 5}
}

WEATHER_SEEDS = [1, 4, 5, 6, 15]
OCCUPANCY_SEEDS = [0, 5, 10]

def run_benchmark(dry_run=False):
    output_dir = REPO_ROOT / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    results = []
    
    # Restrict scope if dry run
    selected_cars = {list(CARS.keys())[0]: list(CARS.values())[0]} if dry_run else CARS
    selected_profiles = {list(PROFILES.keys())[0]: list(PROFILES.values())[0]} if dry_run else PROFILES
    selected_weather = [WEATHER_SEEDS[0]] if dry_run else WEATHER_SEEDS
    selected_occupancy = [OCCUPANCY_SEEDS[0]] if dry_run else OCCUPANCY_SEEDS
    
    total_runs = len(selected_cars) * len(selected_profiles) * len(selected_weather) * len(selected_occupancy)
    print(f"Starting EV Route Planner Benchmark (Dry run = {dry_run})")
    print(f"Total runs to execute: {total_runs}\n")
    
    run_idx = 0
    for car_name, car_id in selected_cars.items():
        try:
            vehicle = find_vehicle_by_id(car_id)
        except Exception as e:
            print(f"Error loading vehicle {car_name} (ID {car_id}): {e}")
            continue
            
        for profile_name, weights in selected_profiles.items():
            for w_seed in selected_weather:
                for o_seed in selected_occupancy:
                    run_idx += 1
                    print(f"[{run_idx}/{total_runs}] Running {car_name} | {profile_name} | Weather seed={w_seed} | Occupancy seed={o_seed}...", end="", flush=True)
                    
                    from api.mocker import set_occupancy_seed
                    set_occupancy_seed(o_seed)
                    
                    prefs = UserPreferences(
                        source=WAYPOINTS[0],
                        destinations=WAYPOINTS[1:],
                        battery_start_pct=80.0,
                        battery_end_min_pct=20.0,
                        battery_capacity_kwh=vehicle.battery_kwh,
                        consumption_kwh_per_100km=vehicle.consumption_kwh_per_100km,
                        range_km=vehicle.range_km,
                        priority_time=weights["time"],
                        priority_cost=weights["cost"],
                        priority_anxiety=weights["anxiety"],
                        battery_min_enroute_pct=15.0,
                        battery_max_enroute_pct=100.0,
                    )
                    
                    start_t = time.time()
                    try:
                        res = plan_journey(prefs, weather_seed=w_seed, waypoint_coords=WAYPOINT_COORDS)
                        elapsed = time.time() - start_t
                        
                        is_partial = any(leg.route.is_partial for leg in res.legs)
                        status = "FAILED (Stranded)" if is_partial else "SUCCESS"
                        
                        # Calculate total stops
                        stops_count = sum(len(leg.route.stops) for leg in res.legs)
                        
                        results.append({
                            "car": car_name,
                            "car_id": car_id,
                            "profile": profile_name,
                            "weather_seed": w_seed,
                            "occupancy_seed": o_seed,
                            "status": status,
                            "distance_km": res.total_distance_km,
                            "time_min": res.total_time_min if not is_partial else np.nan,
                            "cost_tl": res.total_cost if not is_partial else np.nan,
                            "z_score": res.total_z_score if not is_partial else np.nan,
                            "stops": stops_count if not is_partial else 0,
                            "runtime_sec": elapsed
                        })
                        print(f" {status} ({elapsed:.2f}s)")
                        
                    except Exception as e:
                        print(f" ERROR | {e}")
                        results.append({
                            "car": car_name,
                            "car_id": car_id,
                            "profile": profile_name,
                            "weather_seed": w_seed,
                            "occupancy_seed": o_seed,
                            "status": f"ERROR: {type(e).__name__}",
                            "distance_km": np.nan,
                            "time_min": np.nan,
                            "cost_tl": np.nan,
                            "z_score": np.nan,
                            "stops": 0,
                            "runtime_sec": 0
                        })
                        
    df = pd.DataFrame(results)
    csv_path = output_dir / "benchmark_results.csv"
    df.to_csv(csv_path, index=False)
    print(f"\nSaved raw results to: {csv_path}")
    
    if not dry_run:
        generate_plots(df, output_dir)
        
    print("\nBenchmark complete!")


def generate_plots(df, output_dir):
    """Generate professional graphs comparing the vehicles and profiles."""
    print("Generating comparative plots...")
    
    # Filter only successful runs
    success_df = df[df["status"] == "SUCCESS"].copy()
    if success_df.empty:
        print("No successful runs to plot.")
        return
        
    # Group results by car and profile
    grouped = success_df.groupby(["car", "profile"]).agg({
        "time_min": "mean",
        "cost_tl": "mean",
        "z_score": "mean"
    }).reset_index()
    
    cars = list(CARS.keys())
    profiles = list(PROFILES.keys())
    
    # Theme configuration
    colors = {
        "Scenario A (Time)": "#3B82F6",    # Blue
        "Scenario B (Cost)": "#10B981",    # Emerald Green
        "Scenario C (Comfort)": "#F59E0B"   # Amber
    }
    
    # Set global plotting style
    plt.style.use('seaborn-v0_8-whitegrid' if 'seaborn-v0_8-whitegrid' in plt.style.available else 'default')
    plt.rcParams.update({
        'font.size': 11,
        'axes.labelsize': 12,
        'axes.titlesize': 14,
        'xtick.labelsize': 10,
        'ytick.labelsize': 10,
        'figure.titlesize': 16
    })

    # Plot 1: Travel Time Comparison
    fig, ax = plt.subplots(figsize=(10, 6))
    x = np.arange(len(cars))
    width = 0.25
    
    for i, profile in enumerate(profiles):
        means = []
        for car in cars:
            val = grouped[(grouped["car"] == car) & (grouped["profile"] == profile)]["time_min"]
            means.append(val.item() if not val.empty else 0)
        ax.bar(x + (i - 1) * width, means, width, label=profile, color=colors[profile], edgecolor='black', alpha=0.9)
        
    ax.set_ylabel("Average Travel Time (minutes)")
    ax.set_title("Travel Time Comparison across Vehicle Models & Profiles\n(Route: Izmir -> Ankara -> Trabzon)")
    ax.set_xticks(x)
    ax.set_xticklabels(cars)
    ax.legend(title="Weight Profile")
    plt.tight_layout()
    fig.savefig(output_dir / "benchmark_time_comparison.png", dpi=300)
    plt.close(fig)
    
    # Plot 2: Cost Comparison
    fig, ax = plt.subplots(figsize=(10, 6))
    for i, profile in enumerate(profiles):
        means = []
        for car in cars:
            val = grouped[(grouped["car"] == car) & (grouped["profile"] == profile)]["cost_tl"]
            means.append(val.item() if not val.empty else 0)
        ax.bar(x + (i - 1) * width, means, width, label=profile, color=colors[profile], edgecolor='black', alpha=0.9)
        
    ax.set_ylabel("Average Charging Cost (TL)")
    ax.set_title("Total Charging Cost Comparison across Vehicle Models & Profiles\n(Route: Izmir -> Ankara -> Trabzon)")
    ax.set_xticks(x)
    ax.set_xticklabels(cars)
    ax.legend(title="Weight Profile")
    plt.tight_layout()
    fig.savefig(output_dir / "benchmark_cost_comparison.png", dpi=300)
    plt.close(fig)
    
    # Plot 3: Z-Score Comparison
    fig, ax = plt.subplots(figsize=(10, 6))
    for i, profile in enumerate(profiles):
        means = []
        for car in cars:
            val = grouped[(grouped["car"] == car) & (grouped["profile"] == profile)]["z_score"]
            means.append(val.item() if not val.empty else 0)
        ax.bar(x + (i - 1) * width, means, width, label=profile, color=colors[profile], edgecolor='black', alpha=0.9)
        
    ax.set_ylabel("Average Z-Score (Lower is better)")
    ax.set_title("Weighted Z-Score Comparison across Vehicle Models & Profiles\n(Z = w1*Time + w2*Cost + w3*Anxiety)")
    ax.set_xticks(x)
    ax.set_xticklabels(cars)
    ax.legend(title="Weight Profile")
    plt.tight_layout()
    fig.savefig(output_dir / "benchmark_zscore_comparison.png", dpi=300)
    plt.close(fig)
    
    # Plot 4: Z-Score Variability (Box Plot for Baseline Car)
    baseline_car = "Tesla Model 3 Highland"
    baseline_df = success_df[success_df["car"] == baseline_car]
    
    fig, ax = plt.subplots(figsize=(8, 6))
    data_to_plot = [
        baseline_df[baseline_df["profile"] == profile]["z_score"].dropna().tolist()
        for profile in profiles
    ]
    
    bp = ax.boxplot(data_to_plot, labels=profiles, patch_artist=True, medianprops=dict(color='black', linewidth=1.5))
    
    for patch, profile in zip(bp['boxes'], profiles):
        patch.set_facecolor(colors[profile])
        patch.set_edgecolor('black')
        patch.set_alpha(0.8)
        
    ax.set_ylabel("Z-Score")
    ax.set_title(f"Z-Score Variability under Differing Weather/Occupancy Seeds\n(Vehicle: {baseline_car})")
    plt.tight_layout()
    fig.savefig(output_dir / "benchmark_zscore_variability.png", dpi=300)
    plt.close(fig)
    
    print(f"Saved comparison plots to: {output_dir}/")


if __name__ == "__main__":
    # If "dry" argument is passed, run a single dry-run execution
    dry_mode = "dry" in sys.argv
    run_benchmark(dry_run=dry_mode)
