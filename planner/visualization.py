"""
Visualisation: route map and Z-score convergence plot.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from planner.config import UserPreferences
from planner.models import RouteResult


def plot_route(
    result: RouteResult,
    prefs: UserPreferences,
    coords: list[tuple[float, float]],
    station_meta: list[tuple[str, str]],
    dist_mat: np.ndarray,
    road_factor: float,
    save_path: str | Path | None = None,
) -> None:
    """Draw a single route on a lat/lon scatter plot and show it.

    - Origin:       green star
    - Destination:  red square
    - Charging:     blue circles (with name, charge, time)
    - Corridor:     grey dots (unused stations)
    - Arrows:       blue with road-km labels
    """
    import matplotlib.pyplot as plt
    import matplotlib.patheffects as pe
    from matplotlib.lines import Line2D

    n = len(coords)
    all_lons = [c[1] for c in coords]
    all_lats = [c[0] for c in coords]

    path = result.path_node_indices
    path_set = set(path)
    stop_indices = {s.node_index for s in result.stops}

    fig, ax = plt.subplots(figsize=(14, 8))

    # 1. Corridor stations (grey background)
    for i in range(1, n - 1):
        if i not in path_set:
            ax.plot(coords[i][1], coords[i][0], ".", color="#cccccc",
                    markersize=5, zorder=1)

    # 2. Route arrows
    for step in range(len(path) - 1):
        i, j = path[step], path[step + 1]
        xi, yi = coords[i][1], coords[i][0]
        xj, yj = coords[j][1], coords[j][0]
        road_km = dist_mat[i, j] * road_factor

        ax.annotate(
            "", xy=(xj, yj), xytext=(xi, yi),
            arrowprops=dict(arrowstyle="-|>", color="#2563EB", lw=2.0,
                            shrinkA=8, shrinkB=8,
                            connectionstyle="arc3,rad=0.08"),
            zorder=2,
        )
        mx, my = (xi + xj) / 2, (yi + yj) / 2
        ax.text(mx, my, f"{road_km:.0f} km", fontsize=7, color="#1e40af",
                fontweight="bold", ha="center", va="bottom",
                bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none",
                          alpha=0.8),
                zorder=5)

    # 3. Nodes
    outline = [pe.withStroke(linewidth=2.5, foreground="white")]

    # Origin
    ax.plot(coords[0][1], coords[0][0], marker="*", color="#16a34a",
            markersize=20, zorder=10, markeredgecolor="white", markeredgewidth=0.8)
    ax.annotate(
        f"{prefs.source}\n({coords[0][0]:.4f}, {coords[0][1]:.4f})",
        xy=(coords[0][1], coords[0][0]),
        xytext=(12, -18), textcoords="offset points",
        fontsize=8, fontweight="bold", color="#166534",
        path_effects=outline, zorder=11,
    )

    # Destination
    ax.plot(coords[-1][1], coords[-1][0], marker="s", color="#dc2626",
            markersize=14, zorder=10, markeredgecolor="white", markeredgewidth=0.8)
    ax.annotate(
        f"{prefs.destination}\n({coords[-1][0]:.4f}, {coords[-1][1]:.4f})",
        xy=(coords[-1][1], coords[-1][0]),
        xytext=(-12, 14), textcoords="offset points",
        fontsize=8, fontweight="bold", color="#991b1b",
        ha="right", va="bottom", path_effects=outline, zorder=11,
    )

    # Charging stops
    for si, s in enumerate(result.stops):
        i = s.node_index
        ax.plot(coords[i][1], coords[i][0], "o", color="#2563EB",
                markersize=10, zorder=10, markeredgecolor="white",
                markeredgewidth=0.8)
        label = (f"{s.station_name[:25]}\n"
                 f"({coords[i][0]:.4f}, {coords[i][1]:.4f})\n"
                 f"+{s.charge_amount_pct:.0f}%  {s.charge_time_min:.0f}min")
        y_off = 14 if si % 2 == 0 else -14
        va = "bottom" if si % 2 == 0 else "top"
        ax.annotate(label, xy=(coords[i][1], coords[i][0]),
                    xytext=(8, y_off), textcoords="offset points",
                    fontsize=6.5, color="#1e3a5f", va=va,
                    path_effects=outline, zorder=11)

    # Route-through nodes (no charge)
    for idx in path:
        if idx == 0 or idx == n - 1 or idx in stop_indices:
            continue
        ax.plot(coords[idx][1], coords[idx][0], "D", color="#f59e0b",
                markersize=7, zorder=9, markeredgecolor="white",
                markeredgewidth=0.5)

    # 4. Styling
    pad_lon = (max(all_lons) - min(all_lons)) * 0.12 + 0.2
    pad_lat = (max(all_lats) - min(all_lats)) * 0.12 + 0.1
    ax.set_xlim(min(all_lons) - pad_lon, max(all_lons) + pad_lon)
    ax.set_ylim(min(all_lats) - pad_lat, max(all_lats) + pad_lat)
    ax.set_xlabel("Longitude", fontsize=10)
    ax.set_ylabel("Latitude", fontsize=10)
    ax.set_title(
        f"Best Route:  {prefs.source} -> {prefs.destination}\n"
        f"Z={result.z_score:.1f}  |  {result.total_time_min:.0f} min  |  "
        f"{result.total_cost:.0f} TL  |  dest SOC {result.battery_at_destination_pct:.0f}%",
        fontsize=11, fontweight="bold",
    )
    ax.grid(True, alpha=0.3, linestyle="--")

    legend_elems = [
        Line2D([0], [0], marker="*", color="w", markerfacecolor="#16a34a",
               markersize=14, label="Origin"),
        Line2D([0], [0], marker="s", color="w", markerfacecolor="#dc2626",
               markersize=10, label="Destination"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#2563EB",
               markersize=9, label="Charging Stop"),
        Line2D([0], [0], marker=".", color="w", markerfacecolor="#cccccc",
               markersize=8, label="Corridor Station (unused)"),
    ]
    ax.legend(handles=legend_elems, loc="lower left", fontsize=8,
              framealpha=0.9)

    fig.tight_layout()

    if save_path:
        p = Path(save_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(str(p), dpi=150, bbox_inches="tight")
        print(f"Route plot saved: {p.resolve()}")

    plt.show()


def plot_zscore_convergence(
    best_per_gen: list[float],
    source: str,
    destination: str,
    save_path: str | Path | None = None,
) -> None:
    """Plot best Z-score per generation and show it."""
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 5))
    gens = list(range(1, len(best_per_gen) + 1))
    ax.plot(gens, best_per_gen, color="#2563EB", linewidth=2, marker=".", markersize=3)
    ax.set_xlabel("Generation", fontsize=11)
    ax.set_ylabel("Best Z-score", fontsize=11)
    ax.set_title(f"EA Convergence:  {source} -> {destination}", fontsize=12,
                 fontweight="bold")
    ax.grid(True, alpha=0.3, linestyle="--")
    fig.tight_layout()

    if save_path:
        p = Path(save_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(str(p), dpi=150, bbox_inches="tight")
        print(f"Convergence plot saved: {p.resolve()}")

    plt.show()
