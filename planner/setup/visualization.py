"""
Visualisation: route map and Z-score convergence plot.

Supports both single-leg and multi-leg route plotting.
Uses contextily for OpenStreetMap tile backgrounds.

Changes:
  - No individual leg plots — only the combined journey map
  - Journey details (duration, cost, etc.) shown on the combined map
  - Weather squares rendered as semi-transparent coloured rectangles
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from planner.setup.config import UserPreferences
from planner.setup.models import RouteResult, LegResult, MultiLegResult


# ── Per-leg colours for multi-leg plots ──
LEG_COLORS = ["#2563EB", "#dc2626", "#16a34a", "#f59e0b", "#7c3aed",
              "#0891b2", "#be185d", "#65a30d"]


def _get_leg_color(leg_index: int) -> str:
    """Get a colour for a given leg index (cycles if > 8 legs)."""
    return LEG_COLORS[leg_index % len(LEG_COLORS)]


def _add_basemap(ax, zoom="auto"):
    """Attempt to add an OpenStreetMap tile background. Silently skip on failure."""
    try:
        import contextily as ctx
        ctx.add_basemap(ax, crs="EPSG:4326", source=ctx.providers.OpenStreetMap.Mapnik,
                        zoom=zoom, alpha=0.5)
    except Exception:
        ax.set_facecolor("#f0f0f0")


def _draw_route_segment(ax, leg, step, i, j, color, show_km_label=True):
    """Draw one route segment with road polyline or straight-line fallback."""
    coords = leg.coords
    geometries = leg.route_geometries or {}
    road_km = leg.road_km_mat[i, j] if leg.road_km_mat is not None else leg.dist_mat[i, j] * leg.road_factor

    geo = geometries.get((i, j))
    if geo and len(geo) > 2:
        lons = [pt[1] for pt in geo]
        lats = [pt[0] for pt in geo]
        ax.plot(lons, lats, color=color, linewidth=3.0, alpha=0.85, zorder=3,
                solid_capstyle="round")
        # Arrowhead at end
        if len(lons) >= 2:
            ax.annotate("", xy=(lons[-1], lats[-1]), xytext=(lons[-2], lats[-2]),
                        arrowprops=dict(arrowstyle="-|>", color=color, lw=2.5), zorder=4)
        if show_km_label:
            mid = len(geo) // 2
            ax.text(geo[mid][1], geo[mid][0], f"{road_km:.0f} km", fontsize=7,
                    color=color, fontweight="bold", ha="center", va="bottom",
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.9),
                    zorder=6)
    else:
        xi, yi = coords[i][1], coords[i][0]
        xj, yj = coords[j][1], coords[j][0]
        ax.annotate(
            "", xy=(xj, yj), xytext=(xi, yi),
            arrowprops=dict(arrowstyle="-|>", color=color, lw=2.5,
                            shrinkA=6, shrinkB=6,
                            connectionstyle="arc3,rad=0.08"),
            zorder=3,
        )
        if show_km_label:
            mx, my = (xi + xj) / 2, (yi + yj) / 2
            ax.text(mx, my, f"{road_km:.0f} km", fontsize=7, color=color,
                    fontweight="bold", ha="center", va="bottom",
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.9),
                    zorder=6)


# ---------------------------------------------------------------------------
# Weather square colours — red scale based on severity
# ---------------------------------------------------------------------------

def _weather_color(quality: float) -> str:
    """Map weather quality (0-1) to a colour. Lower = worse = more red."""
    # Interpolate from deep red (0.0) to light orange (0.8)
    r = 1.0
    g = quality * 0.8   # 0 -> 0, 0.8 -> 0.64
    b = quality * 0.3   # 0 -> 0, 0.8 -> 0.24
    return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"


def _draw_weather_squares(ax, weather_squares, legend_elems):
    """Draw semi-transparent weather squares on the map and add to legend."""
    import matplotlib.patches as mpatches

    if not weather_squares:
        return

    for idx, sq in enumerate(weather_squares):
        width = sq.lon_max - sq.lon_min
        height = sq.lat_max - sq.lat_min
        color = _weather_color(sq.quality)
        rect = mpatches.Rectangle(
            (sq.lon_min, sq.lat_min), width, height,
            linewidth=1.5, edgecolor=color, facecolor=color,
            alpha=0.18, zorder=1, linestyle="--",
        )
        ax.add_patch(rect)

        # Add label at centre of the square
        cx = sq.lon_min + width / 2
        cy = sq.lat_min + height / 2
        ax.text(cx, cy, f"q={sq.quality:.2f}", fontsize=7, ha="center", va="center",
                color=color, fontweight="bold", alpha=0.7, zorder=2)

    # Add a single legend entry for weather zones
    legend_elems.append(
        mpatches.Patch(facecolor="#ff4444", alpha=0.18, edgecolor="#ff4444",
                       linestyle="--", label=f"Weather Zone ({len(weather_squares)} zones)")
    )


# ---------------------------------------------------------------------------
# Combined multi-leg map with journey details (the MAIN plot)
# ---------------------------------------------------------------------------

def plot_multi_leg(multi: MultiLegResult, save_path: str | Path | None = None) -> None:
    """Plot all legs of a multi-leg journey on one combined map.
    
    - Each leg has its own colour
    - Unused stations: dark grey circles  
    - Road polylines from cache
    - Tile map background
    - Journey details (duration, cost, Z-score) displayed as a text box
    - Weather squares rendered as semi-transparent overlays
    """
    import matplotlib.pyplot as plt
    import matplotlib.patheffects as pe
    from matplotlib.lines import Line2D

    fig, ax = plt.subplots(figsize=(16, 9))
    outline = [pe.withStroke(linewidth=3, foreground="white")]

    all_lons = []
    all_lats = []

    # Collect all path node indices across all legs (to distinguish used vs unused)
    all_path_nodes: dict[int, set[int]] = {}  # leg_idx -> set of node indices in path
    for leg in multi.legs:
        path_set = set(leg.route.path_node_indices)
        all_path_nodes[leg.leg_index] = path_set

    # 1. Draw weather squares FIRST (lowest z-order)
    legend_elems = []
    _draw_weather_squares(ax, multi.weather_squares, legend_elems)

    # 2. Base map: draw all unused corridor stations
    for leg in multi.legs:
        path_set = all_path_nodes[leg.leg_index]
        n = len(leg.coords)
        for ci in range(1, n - 1):
            all_lats.append(leg.coords[ci][0])
            all_lons.append(leg.coords[ci][1])
            if ci not in path_set:
                ax.plot(leg.coords[ci][1], leg.coords[ci][0], "o",
                        color="#9ca3af", markersize=4, zorder=1, alpha=0.5,
                        markeredgecolor="#6b7280", markeredgewidth=0.2)

        # Include origin/dest in bounds
        all_lats.append(leg.coords[0][0])
        all_lons.append(leg.coords[0][1])
        all_lats.append(leg.coords[-1][0])
        all_lons.append(leg.coords[-1][1])

    # 3. Draw each leg's route
    for leg_idx, leg in enumerate(multi.legs):
        color = _get_leg_color(leg_idx)
        path = leg.route.path_node_indices

        # Road segments
        for step in range(len(path) - 1):
            i, j = path[step], path[step + 1]
            _draw_route_segment(ax, leg, step, i, j, color, show_km_label=True)

        # Charging stops
        for s in leg.route.stops:
            i = s.node_index
            ax.plot(leg.coords[i][1], leg.coords[i][0], "o", color=color,
                    markersize=10, zorder=11, markeredgecolor="white", markeredgewidth=0.8)
            label = f"+{s.charge_amount_pct:.0f}% ({s.charge_time_min:.0f}m)"
            ax.annotate(label, xy=(leg.coords[i][1], leg.coords[i][0]),
                        xytext=(6, 8), textcoords="offset points",
                        fontsize=7, color="#1e3a5f", path_effects=outline, zorder=14)

    # 4. Draw Waypoints (Origins & Final Destination)
    for leg_idx, leg in enumerate(multi.legs):
        c = leg.coords[0]
        ax.plot(c[1], c[0], marker="*", color="#16a34a",
                markersize=20, zorder=15, markeredgecolor="white", markeredgewidth=1.0)
        ax.annotate(leg.origin.split(',')[0], xy=(c[1], c[0]),
                    xytext=(0, -16), textcoords="offset points",
                    fontsize=9, fontweight="bold", ha="center", path_effects=outline, zorder=16)
        
        if leg_idx == len(multi.legs) - 1:
            c_dest = leg.coords[-1]
            ax.plot(c_dest[1], c_dest[0], marker="s", color="#dc2626",
                    markersize=15, zorder=15, markeredgecolor="white", markeredgewidth=1.0)
            ax.annotate(leg.destination.split(',')[0], xy=(c_dest[1], c_dest[0]),
                        xytext=(0, 14), textcoords="offset points",
                        fontsize=9, fontweight="bold", ha="center", path_effects=outline, zorder=16)

    # 5. Styling + basemap
    if all_lons and all_lats:
        pad_lon = (max(all_lons) - min(all_lons)) * 0.12 + 0.01
        pad_lat = (max(all_lats) - min(all_lats)) * 0.12 + 0.005
        ax.set_xlim(min(all_lons) - pad_lon, max(all_lons) + pad_lon)
        ax.set_ylim(min(all_lats) - pad_lat, max(all_lats) + pad_lat)

    _add_basemap(ax)

    ax.set_xlabel("Longitude", fontsize=10)
    ax.set_ylabel("Latitude", fontsize=10)

    # 6. Title with journey details
    ax.set_title(
        f"Full Journey: {multi.itinerary}\n"
        f"Total Distance: {multi.total_distance_km:.0f} km  |  "
        f"Total Time: {multi.total_time_min:.0f} min  |  "
        f"Drive: {multi.total_drive_time_min:.0f} min  |  "
        f"Charge: {multi.total_charge_time_min:.0f} min  |  "
        f"Cost: {multi.total_cost:.0f} TL  |  "
        f"Z: {multi.total_z_score:.1f}  |  "
        f"Final SOC: {multi.battery_at_final_dest:.0f}%",
        fontsize=11, fontweight="bold",
    )

    # 7. Build legend
    base_legend = [
        Line2D([0], [0], marker="*", color="w", markerfacecolor="#16a34a",
               markersize=14, label="Waypoint"),
        Line2D([0], [0], marker="s", color="w", markerfacecolor="#dc2626",
               markersize=10, label="Final Dest"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#9ca3af",
               markersize=6, label="Unused Station"),
    ]
    for leg_idx, leg in enumerate(multi.legs):
        c = _get_leg_color(leg_idx)
        lbl = (f"Leg {leg_idx+1}: {leg.origin.split(',')[0]}→{leg.destination.split(',')[0]}  "
               f"({leg.route.total_time_min:.0f}m, {leg.route.total_cost:.0f}TL)")
        base_legend.append(Line2D([0], [0], color=c, linewidth=2.5, label=lbl))

    # Combine base legend + weather legend
    all_legend = base_legend + legend_elems
    ax.legend(handles=all_legend, loc="lower left", fontsize=8, framealpha=0.9)

    # 8. Per-leg info box in top-right corner
    info_lines = []
    for leg in multi.legs:
        r = leg.route
        n_stops = len(r.stops)
        info_lines.append(
            f"Leg {leg.leg_index+1}: {leg.origin.split(',')[0]}→{leg.destination.split(',')[0]}  "
            f"| {r.total_distance_km:.0f} km | {r.total_time_min:.0f} min | {r.total_cost:.0f} TL | "
            f"{n_stops} stop{'s' if n_stops != 1 else ''} | "
            f"SOC {r.battery_at_destination_pct:.0f}%"
        )
    info_text = "\n".join(info_lines)
    ax.text(0.99, 0.99, info_text, transform=ax.transAxes,
            fontsize=7.5, verticalalignment="top", horizontalalignment="right",
            fontfamily="monospace",
            bbox=dict(boxstyle="round,pad=0.5", facecolor="white", alpha=0.85,
                      edgecolor="#cccccc"),
            zorder=20)

    fig.tight_layout()

    if save_path:
        p = Path(save_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(str(p), dpi=200, bbox_inches="tight")
        print(f"  Journey map saved: {p.resolve()}")


# ---------------------------------------------------------------------------
# Z-score convergence (single leg)
# ---------------------------------------------------------------------------

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
        print(f"  Convergence plot saved: {p.resolve()}")


# ---------------------------------------------------------------------------
# Multi-leg convergence (all legs on one plot, ALL generations)
# ---------------------------------------------------------------------------

def plot_multi_leg_convergence(
    multi: MultiLegResult,
    save_path: str | Path | None = None,
) -> None:
    """Plot convergence curves for all legs on one figure. Shows ALL generations."""
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(12, 6))

    for leg in multi.legs:
        color = _get_leg_color(leg.leg_index)
        gens = list(range(1, len(leg.convergence) + 1))
        label = f"Leg {leg.leg_index + 1}: {leg.origin.split(',')[0]} → {leg.destination.split(',')[0]}"
        ax.plot(gens, leg.convergence, color=color, linewidth=2,
                marker=".", markersize=3, label=label)

    ax.set_xlabel("Generation", fontsize=11)
    ax.set_ylabel("Best Z-score", fontsize=11)
    ax.set_title(f"EA Convergence — {multi.itinerary}\n({len(multi.legs[0].convergence)} generations)",
                 fontsize=11, fontweight="bold")
    ax.legend(fontsize=9, framealpha=0.9)
    ax.grid(True, alpha=0.3, linestyle="--")
    fig.tight_layout()

    if save_path:
        p = Path(save_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(str(p), dpi=150, bbox_inches="tight")
        print(f"  Multi-leg convergence plot saved: {p.resolve()}")


# ---------------------------------------------------------------------------
# Master display function
# ---------------------------------------------------------------------------

def show_all_plots(multi: MultiLegResult, save_dir: str | Path, save_name: str) -> None:
    """Display all plots simultaneously in separate windows.
    
    Windows:
      - One combined multi-leg map with journey details and weather (saved to disk)
      - One convergence plot for all legs (saved to disk)
    
    NOTE: Individual leg plots have been removed. All details are shown on
    the combined map via the title, legend, and info box.
    """
    import matplotlib.pyplot as plt

    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    # 1. Combined multi-leg map with details and weather (saved)
    multi_route_save = save_dir / f"{save_name}_full_journey_map.png"
    plot_multi_leg(multi, save_path=multi_route_save)

    # 2. Convergence plot (saved)
    multi_conv_save = save_dir / f"{save_name}_all_convergence.png"
    plot_multi_leg_convergence(multi, save_path=multi_conv_save)

    # Show all at once
    plt.show()
