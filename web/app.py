"""
EV Route Planner — Streamlit Web App (Jury Demo)

Mobile-first interface wrapping the existing CLI pipeline.
Launches with:  streamlit run web/app.py
"""
# ── Matplotlib backend MUST be set before any pyplot import ──
import matplotlib
matplotlib.use("Agg")

import io
import sys
import socket
import datetime
import threading
from pathlib import Path

# ── Ensure project root is on sys.path ──
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st
import matplotlib.pyplot as plt
import folium
from streamlit_folium import st_folium

# ── Page config (must be the first Streamlit command) ──
st.set_page_config(
    page_title="EV Route Planner",
    page_icon="⚡",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ── Load custom CSS ──
CSS_PATH = Path(__file__).parent / "style.css"
if CSS_PATH.exists():
    st.markdown(f"<style>{CSS_PATH.read_text(encoding='utf-8')}</style>",
                unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════
# Imports from the codebase
# ═══════════════════════════════════════════════════════════
# ── Force reload backend modules to avoid Streamlit import caching issues ──
import importlib
import planner.setup.config
import planner.setup.models
import planner.setup.routing_cache
import planner.setup.tomtom
import planner.setup.matrices
import planner.setup.ea_solver
import planner.pipeline

importlib.reload(planner.setup.config)
importlib.reload(planner.setup.models)
importlib.reload(planner.setup.routing_cache)
importlib.reload(planner.setup.tomtom)
importlib.reload(planner.setup.matrices)
importlib.reload(planner.setup.ea_solver)
importlib.reload(planner.pipeline)

from planner.setup.ev_vehicle import (
    load_ev_database, _extract_car_id, _clean_name, find_vehicle_by_id,
)
from planner.setup.config import UserPreferences, BASE_VELOCITY_KMH, CRUISE_VELOCITY_KMH
from planner.pipeline import plan_journey
from planner.setup.visualization import plot_multi_leg, plot_multi_leg_convergence
from api.mocker import set_occupancy_seed


# ═══════════════════════════════════════════════════════════
# Session state initialization
# ═══════════════════════════════════════════════════════════
if "plot_history" not in st.session_state:
    st.session_state.plot_history = []   # list of dicts, newest first, max 5

if "map_waypoints" not in st.session_state:
    st.session_state.map_waypoints = []

if "last_clicked" not in st.session_state:
    st.session_state.last_clicked = None


# ═══════════════════════════════════════════════════════════
# Stdout capture for live logging
# ═══════════════════════════════════════════════════════════
class LogCapture:
    """Captures stdout writes to a buffer while still printing to the console and Streamlit."""

    def __init__(self, st_placeholder=None):
        self._buffer = io.StringIO()
        self._original_stdout = None
        self._lock = threading.Lock()
        self._st_placeholder = st_placeholder

    def start(self):
        if getattr(sys.stdout, "_original_stdout", None) is not None:
            self._original_stdout = sys.stdout._original_stdout
        else:
            self._original_stdout = sys.stdout
        sys.stdout = self

    def stop(self):
        if self._original_stdout is not None:
            sys.stdout = self._original_stdout
            self._original_stdout = None

    def write(self, text):
        with self._lock:
            self._buffer.write(text)
            if self._original_stdout:
                try:
                    self._original_stdout.write(text)
                except Exception:
                    pass
            
            # Live update in Streamlit (shows last ~40 lines to avoid UI lag)
            if self._st_placeholder:
                lines = self._buffer.getvalue().splitlines()
                display_text = "\n".join(lines[-40:]) if len(lines) > 40 else self._buffer.getvalue()
                self._st_placeholder.code(display_text, language="text")

    def flush(self):
        if self._original_stdout:
            self._original_stdout.flush()

    def getvalue(self):
        with self._lock:
            return self._buffer.getvalue()


# ═══════════════════════════════════════════════════════════
# Vehicle data loader (cached)
# ═══════════════════════════════════════════════════════════
@st.cache_data(show_spinner=False)
def get_vehicle_options():
    """Load EV database → sorted list of (display_name, car_id)."""
    db = load_ev_database()
    vehicles = []
    for entry in db:
        car_id = _extract_car_id(entry.get("href", ""))
        if car_id is None:
            continue
        name = _clean_name(entry.get("name", "Unknown"))
        battery = entry.get("battery_kwh", 0)
        range_km = entry.get("range_km", 0)
        eff = entry.get("efficiency_wh_per_km", 0)
        display = f"{name}  —  {battery:.0f} kWh, {range_km:.0f} km, {eff:.0f} Wh/km"
        
        # Extract brand (first word by default, handling multi-word brand cases)
        brand = name.split()[0] if name.split() else "Unknown"
        if name.lower().startswith("alfa romeo"):
            brand = "Alfa Romeo"
        elif name.lower().startswith("aston martin"):
            brand = "Aston Martin"
            
        vehicles.append({"display": display, "car_id": car_id, "name": name, "brand": brand})
    # Sort alphabetically by name
    vehicles.sort(key=lambda v: v["name"].lower())
    return vehicles


# ═══════════════════════════════════════════════════════════
# QR code helper
# ═══════════════════════════════════════════════════════════
def get_local_ip():
    """Get the machine's LAN IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def render_qr_sidebar():
    """Render QR code and access URL in the sidebar."""
    try:
        import qrcode
    except ImportError:
        st.sidebar.warning("Install `qrcode[pil]` for QR code support.")
        return

    with st.sidebar:
        st.header("📱 Demo Access")
        local_ip = get_local_ip()
        url = f"http://{local_ip}:8501"

        qr = qrcode.make(url)
        buf = io.BytesIO()
        qr.save(buf, format="PNG")
        buf.seek(0)

        st.markdown('<div class="qr-container">', unsafe_allow_html=True)
        st.image(buf, width=200)
        st.markdown('</div>', unsafe_allow_html=True)

        st.code(url, language=None)
        st.caption("📶 Ensure your phone is on the same Wi-Fi network as this computer.")


# ═══════════════════════════════════════════════════════════
# Plot generation helpers
# ═══════════════════════════════════════════════════════════
def generate_map_image(result):
    """Generate the journey map as a PNG bytes buffer for history (fallback)."""
    plot_multi_leg(result, save_path=None)
    fig = plt.gcf()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=180, bbox_inches="tight",
                facecolor="#0f172a", edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    return buf

def generate_folium_map(result):
    """Generate an interactive Folium map for the journey."""
    all_lats, all_lons = [], []
    for leg in result.legs:
        for lat, lon in leg.coords:
            all_lats.append(lat)
            all_lons.append(lon)
            
    if not all_lats:
        return folium.Map(location=[39.0, 35.0], zoom_start=6)
        
    avg_lat = sum(all_lats) / len(all_lats)
    avg_lon = sum(all_lons) / len(all_lons)
    
    m = folium.Map(location=[avg_lat, avg_lon], zoom_start=6, tiles="CartoDB positron")
    
    LEG_COLORS = ["#2563EB", "#dc2626", "#16a34a", "#f59e0b", "#7c3aed", "#0891b2", "#be185d", "#65a30d"]
    
    for leg_idx, leg in enumerate(result.legs):
        color = LEG_COLORS[leg_idx % len(LEG_COLORS)]
        
        # Route geometry
        path = leg.route.path_node_indices
        for step in range(len(path) - 1):
            i, j = path[step], path[step + 1]
            geo = leg.route_geometries.get((i, j))
            if geo and len(geo) > 1:
                folium.PolyLine(locations=geo, color=color, weight=4, opacity=0.8).add_to(m)
            else:
                folium.PolyLine(locations=[leg.coords[i], leg.coords[j]], color=color, weight=4, opacity=0.8).add_to(m)
                
        # Stops
        for s in leg.route.stops:
            i = s.node_index
            lat, lon = leg.coords[i]
            popup_html = f"<b>{s.station_name}</b><br>{s.max_kw:.0f} kW<br>Charge: +{s.charge_amount_pct:.0f}%<br>Time: {s.charge_time_min:.0f} min"
            folium.CircleMarker(
                location=[lat, lon],
                radius=8,
                popup=popup_html,
                color="white",
                fill=True,
                fillColor=color,
                fillOpacity=1.0,
                weight=2
            ).add_to(m)
            
        # Origin
        folium.Marker(
            location=leg.coords[0],
            popup=leg.origin,
            icon=folium.Icon(color="green", icon="play")
        ).add_to(m)
        
        # Destination
        if leg_idx == len(result.legs) - 1:
            folium.Marker(
                location=leg.coords[-1],
                popup=leg.destination,
                icon=folium.Icon(color="red", icon="flag")
            ).add_to(m)
            
    m.fit_bounds([[min(all_lats), min(all_lons)], [max(all_lats), max(all_lons)]])
    return m

def generate_convergence_image(result):
    """Generate the convergence plot as a PNG bytes buffer."""
    plot_multi_leg_convergence(result, save_path=None)
    fig = plt.gcf()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor="#0f172a", edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    return buf


# ═══════════════════════════════════════════════════════════
# Plot history management
# ═══════════════════════════════════════════════════════════
def save_to_history(result, map_buf, conv_buf, log_text=""):
    """Cache the run in session state (max 5 entries, newest first)."""
    entry = {
        "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
        "itinerary": result.itinerary,
        "total_time_min": result.total_time_min,
        "total_cost": result.total_cost,
        "total_z_score": result.total_z_score,
        "battery_end": result.battery_at_final_dest,
        "total_distance_km": result.total_distance_km,
        "map_png": map_buf.getvalue(),
        "conv_png": conv_buf.getvalue(),
        "log_text": log_text,
        "legs": [],
    }
    for leg in result.legs:
        r = leg.route
        entry["legs"].append({
            "origin": leg.origin,
            "destination": leg.destination,
            "distance_km": r.total_distance_km,
            "time_min": r.total_time_min,
            "cost": r.total_cost,
            "z_score": r.z_score,
            "end_soc": r.battery_at_destination_pct,
            "stops": [
                {
                    "name": s.station_name,
                    "kw": s.max_kw,
                    "arrive_pct": s.battery_on_arrival_pct,
                    "charge_pct": s.charge_amount_pct,
                    "depart_pct": s.battery_on_departure_pct,
                    "time_min": s.charge_time_min,
                    "cost": s.charge_cost,
                }
                for s in r.stops
            ],
        })
    history = st.session_state.plot_history
    history.insert(0, entry)
    st.session_state.plot_history = history[:5]


def render_history_sidebar():
    """Render past runs in the sidebar."""
    history = st.session_state.plot_history
    if not history:
        return

    with st.sidebar:
        st.markdown("---")
        st.header("🕘 Recent Runs")
        st.caption(f"{len(history)} run(s) cached this session")

        for idx, entry in enumerate(history):
            with st.expander(
                f"**{entry['itinerary']}** — {entry['timestamp']}",
                expanded=False,
            ):
                c1, c2 = st.columns(2)
                c1.metric("⏱ Time", f"{entry['total_time_min']:.0f} min")
                c2.metric("💰 Cost", f"{entry['total_cost']:.0f} TL")
                c3, c4 = st.columns(2)
                c3.metric("📊 Z-score", f"{entry['total_z_score']:.2f}")
                c4.metric("🔋 SOC", f"{entry['battery_end']:.0f}%")

                st.image(entry["map_png"], caption="Route Map (Static)",
                         width='stretch')
                st.image(entry["conv_png"], caption="Convergence",
                         width='stretch')

                if entry.get("log_text"):
                    with st.expander("📋 Pipeline Logs"):
                        st.code(entry["log_text"], language="text")


# ═══════════════════════════════════════════════════════════
# Results rendering
# ═══════════════════════════════════════════════════════════
def render_results(result, map_buf, conv_buf, log_text=""):
    """Display results after a successful pipeline run."""

    # ── Success banner ──
    st.markdown(
        '<div class="success-banner">'
        '<span class="success-text">✅ Route optimized successfully!</span>'
        '</div>',
        unsafe_allow_html=True,
    )

    # ── Metric cards ──
    total_hrs = result.total_time_min / 60
    time_str = (f"{int(total_hrs)}h {int(result.total_time_min % 60)}m"
                if total_hrs >= 1 else f"{result.total_time_min:.0f} min")

    st.markdown(
        f"""
        <div class="metric-row">
            <div class="metric-card">
                <div class="metric-icon">🕐</div>
                <div class="metric-value">{time_str}</div>
                <div class="metric-label">Total Time</div>
            </div>
            <div class="metric-card">
                <div class="metric-icon">💰</div>
                <div class="metric-value">{result.total_cost:.0f} TL</div>
                <div class="metric-label">Cost</div>
            </div>
            <div class="metric-card">
                <div class="metric-icon">📊</div>
                <div class="metric-value">{result.total_z_score:.2f}</div>
                <div class="metric-label">Z-Score</div>
            </div>
            <div class="metric-card">
                <div class="metric-icon">🔋</div>
                <div class="metric-value">{result.battery_at_final_dest:.0f}%</div>
                <div class="metric-label">Final SOC</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Extra stats row ──
    st.markdown(
        f"""
        <div class="metric-row">
            <div class="metric-card">
                <div class="metric-icon">📏</div>
                <div class="metric-value">{result.total_distance_km:.0f} km</div>
                <div class="metric-label">Distance</div>
            </div>
            <div class="metric-card">
                <div class="metric-icon">🚗</div>
                <div class="metric-value">{result.total_drive_time_min:.0f} m</div>
                <div class="metric-label">Drive</div>
            </div>
            <div class="metric-card">
                <div class="metric-icon">🔌</div>
                <div class="metric-value">{result.total_charge_time_min:.0f} m</div>
                <div class="metric-label">Charge</div>
            </div>
            <div class="metric-card">
                <div class="metric-icon">🦶</div>
                <div class="metric-value">{len(result.legs)}</div>
                <div class="metric-label">Legs</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Journey map (Interactive Folium) ──
    st.markdown('<div class="section-label">🗺️ Interactive Map</div>',
                unsafe_allow_html=True)
    st.markdown('<div class="map-container">', unsafe_allow_html=True)
    folium_map = generate_folium_map(result)
    st_folium(folium_map, use_container_width=True, height=500, returned_objects=[])
    st.markdown('</div>', unsafe_allow_html=True)

    # ── Journey map (Static) ──
    st.markdown('<div class="section-label">🗺️ Static Map (Network & Unused Stations)</div>',
                unsafe_allow_html=True)
    st.markdown('<div class="map-container">', unsafe_allow_html=True)
    st.image(map_buf, width='stretch')
    st.markdown('</div>', unsafe_allow_html=True)

    # ── Per-leg details table ──
    if len(result.legs) > 0:
        st.markdown('<div class="section-label">📋 Leg Details</div>',
                    unsafe_allow_html=True)
        rows = ""
        for leg in result.legs:
            r = leg.route
            origin_short = leg.origin.split(",")[0]
            dest_short = leg.destination.split(",")[0]
            n_stops = len(r.stops)
            rows += (
                f"<tr>"
                f"<td><strong>{leg.leg_index + 1}</strong></td>"
                f"<td>{origin_short} → {dest_short}</td>"
                f"<td>{r.total_distance_km:.0f}</td>"
                f"<td>{r.total_time_min:.0f}</td>"
                f"<td>{r.total_cost:.0f}</td>"
                f"<td>{r.z_score:.2f}</td>"
                f"<td>{n_stops}</td>"
                f"<td>{r.battery_at_destination_pct:.0f}%</td>"
                f"</tr>"
            )
        st.markdown(
            f"""
            <table class="leg-table">
                <thead>
                    <tr>
                        <th>#</th><th>Route</th><th>km</th>
                        <th>min</th><th>TL</th><th>Z</th>
                        <th>Stops</th><th>SOC</th>
                    </tr>
                </thead>
                <tbody>{rows}</tbody>
            </table>
            """,
            unsafe_allow_html=True,
        )

    # ── Charging stop details (always visible if present) ──
    has_stops = any(leg.route.stops for leg in result.legs)
    if has_stops:
        st.markdown('<div class="section-label">🔌 Charging Stop Details</div>',
                    unsafe_allow_html=True)
        for leg in result.legs:
            if not leg.route.stops:
                continue
            st.markdown(
                f"**Leg {leg.leg_index + 1}: "
                f"{leg.origin.split(',')[0]} → {leg.destination.split(',')[0]}**"
            )
            for s in leg.route.stops:
                st.markdown(
                    f"""
                    <div class="stop-card">
                        <div class="stop-name">⚡ {s.station_name}
                            <span style="color:#64748b;font-size:0.75rem">
                                ({s.max_kw:.0f} kW)
                            </span>
                        </div>
                        <div class="stop-detail">
                            Arrive {s.battery_on_arrival_pct:.0f}%
                            → Charge +{s.charge_amount_pct:.0f}%
                            → Depart {s.battery_on_departure_pct:.0f}%
                            &nbsp;|&nbsp; {s.charge_time_min:.0f} min
                            &nbsp;|&nbsp; {s.charge_cost:.0f} TL
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    # ── Segment Speed Profiles ──
    st.markdown('<div class="section-label">🚗 Speed Profiles per Segment</div>',
                unsafe_allow_html=True)
    for leg in result.legs:
        r = leg.route
        st.markdown(f"**Leg {leg.leg_index + 1}: {leg.origin.split(',')[0]} → {leg.destination.split(',')[0]}**")
        
        path = r.path_node_indices
        speeds = getattr(r, "segment_speeds", [])
        
        # Build segment descriptions
        for step in range(len(path) - 1):
            i, j = path[step], path[step + 1]
            
            # Get names
            if i == 0:
                name_i = leg.origin.split(",")[0]
            else:
                name_i = leg.station_meta[i - 1][1].split(",")[0]
                
            if j == len(leg.coords) - 1:
                name_j = leg.destination.split(",")[0]
            else:
                name_j = leg.station_meta[j - 1][1].split(",")[0]
                
            speed_val = speeds[step] if step < len(speeds) else CRUISE_VELOCITY_KMH
            
            st.markdown(
                f"""
                <div class="stop-card" style="border-left: 4px solid #2563eb; background: #1e293b;">
                    <div style="font-weight: 600; color: #f8fafc; font-size: 0.9rem;">
                        📍 {name_i} &nbsp;➡&nbsp; {name_j}
                    </div>
                    <div class="stop-detail" style="margin-top: 4px; color: #94a3b8;">
                        ⚡ Target Speed: <strong>{speed_val:.0f} km/h</strong> (eco-ratio: {speed_val/BASE_VELOCITY_KMH:.2f}x)
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    # ── Convergence plot (collapsible) ──
    with st.expander("📈 Algorithm Convergence", expanded=False):
        st.image(conv_buf, caption="Z-score convergence per generation",
                 width='stretch')

    # ── Pipeline logs (collapsible) ──
    if log_text:
        with st.expander("📋 Pipeline Logs", expanded=False):
            st.code(log_text, language="text")


# ═══════════════════════════════════════════════════════════
# MAIN APP
# ═══════════════════════════════════════════════════════════
def main():
    # ── Sidebar: QR + History ──
    render_qr_sidebar()
    render_history_sidebar()

    # ── Header ──
    st.markdown(
        """
        <div class="app-header">
            <h1>⚡ EV Route Planner</h1>
            <p>Optimize your electric vehicle journey across Turkey with evolutionary AI</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Load vehicle data ──
    vehicles = get_vehicle_options()
    display_names = [v["display"] for v in vehicles]
    car_ids = [v["car_id"] for v in vehicles]

    # Default selection: Tesla Model 3 RWD (car_id 3403) if available
    default_idx = 0
    for i, v in enumerate(vehicles):
        if v["car_id"] == 3403:
            default_idx = i
            break

    # ── Vehicle selector ──
    st.markdown('<div class="section-label">🔌 Vehicle</div>',
                unsafe_allow_html=True)
    
    # Extract unique brands and sort them
    brands = sorted(list(set(v["brand"] for v in vehicles)))
    brands_options = ["All Brands"] + brands
    
    col_brand, col_model = st.columns([1, 2])
    with col_brand:
        selected_brand = st.selectbox(
            "Brand",
            brands_options,
            index=0,
            label_visibility="collapsed",
        )
        
    # Filter vehicles by brand
    if selected_brand != "All Brands":
        filtered_vehicles = [v for v in vehicles if v["brand"] == selected_brand]
    else:
        filtered_vehicles = vehicles
        
    display_names = [v["display"] for v in filtered_vehicles]
    car_ids = [v["car_id"] for v in filtered_vehicles]

    # Default selection: Tesla Model 3 RWD (car_id 3403) if available
    default_idx = 0
    for i, v in enumerate(filtered_vehicles):
        if v["car_id"] == 3403:
            default_idx = i
            break

    with col_model:
        selected_idx = st.selectbox(
            "Select your EV",
            range(len(display_names)),
            index=default_idx,
            format_func=lambda i: display_names[i],
            label_visibility="collapsed",
        )
    selected_car_id = car_ids[selected_idx]

    # ── Source / Destination ──
    st.markdown('<div class="section-label">📍 Route Input Mode</div>',
                unsafe_allow_html=True)
    input_mode = st.radio(
        "Select how you want to input your route:",
        options=["📝 Text Mode", "🗺️ Map Mode"],
        horizontal=True,
        label_visibility="collapsed",
    )

    if input_mode == "📝 Text Mode":
        st.markdown('<div class="section-label">📍 Route Details</div>',
                    unsafe_allow_html=True)
        source = st.text_input(
            "Source",
            value="Izmir, Turkey",
            placeholder='e.g. "Izmir, Turkey"',
            label_visibility="collapsed",
            help='Enter a city name, e.g. "Izmir, Turkey" or "Ankara".',
        )

        destinations_raw = st.text_area(
            "Destinations",
            value="Ankara, Turkey",
            height=80,
            placeholder='One destination per line:\nAnkara, Turkey\nIstanbul, Turkey',
            label_visibility="collapsed",
            help=(
                'Enter one destination per line. For multi-leg journeys, list them in '
                'order. Format: "City, Country" (e.g. "Ankara, Turkey").'
            ),
        )
    else:
        st.markdown('<div class="section-label">🗺️ Map Waypoint Picker</div>',
                    unsafe_allow_html=True)
        st.caption("Click on the map to add stops in order. First click is the Source (green marker).")
        
        # Load API key and render Folium map
        from planner.setup.tomtom import load_api_key
        api_key = load_api_key()
        
        m = folium.Map(location=[39.0, 35.0], zoom_start=6, tiles="CartoDB positron")
        
        # Add markers for current waypoints
        for idx, wp in enumerate(st.session_state.map_waypoints):
            lat = wp["lat"]
            lon = wp["lon"]
            label = wp["label"]
            if idx == 0:
                color = "green"
                icon = "play"
            elif idx == len(st.session_state.map_waypoints) - 1:
                color = "red"
                icon = "flag"
            else:
                color = "blue"
                icon = "info-sign"
            
            folium.Marker(
                location=[lat, lon],
                popup=f"{idx+1}. {label}",
                icon=folium.Icon(color=color, icon=icon)
            ).add_to(m)
            
        if len(st.session_state.map_waypoints) > 1:
            locs = [[wp["lat"], wp["lon"]] for wp in st.session_state.map_waypoints]
            folium.PolyLine(locations=locs, color="#2563eb", weight=3, opacity=0.7, dash_array="5, 5").add_to(m)
            
        # Display the map and capture clicks
        map_data = st_folium(m, center=[39.0, 35.0], zoom=6, width=700, height=450, returned_objects=["last_clicked"])
        
        if map_data and map_data.get("last_clicked"):
            click = map_data["last_clicked"]
            if click != st.session_state.last_clicked:
                st.session_state.last_clicked = click
                lat = click["lat"]
                lon = click["lng"]
                
                with st.spinner("Reverse geocoding..."):
                    try:
                        from planner.setup.tomtom import reverse_geocode
                        label = reverse_geocode(lat, lon, api_key)
                    except Exception:
                        label = f"Waypoint {len(st.session_state.map_waypoints) + 1}"
                
                st.session_state.map_waypoints.append({
                    "lat": lat,
                    "lon": lon,
                    "label": label
                })
                st.rerun()
                
        # Waypoints status and buttons
        if st.session_state.map_waypoints:
            st.markdown("**Selected Waypoints:**")
            for idx, wp in enumerate(st.session_state.map_waypoints):
                icon = "🟢" if idx == 0 else ("🔴" if idx == len(st.session_state.map_waypoints) - 1 else "🔵")
                st.markdown(f"{icon} **Waypoint {idx+1}:** {wp['label']} `({wp['lat']:.4f}, {wp['lon']:.4f})`")
            
            c1, c2 = st.columns(2)
            with c1:
                if st.button("↩️ Undo Last", width='stretch'):
                    if st.session_state.map_waypoints:
                        st.session_state.map_waypoints.pop()
                    st.rerun()
            with c2:
                if st.button("🗑️ Clear All", width='stretch'):
                    st.session_state.map_waypoints = []
                    st.rerun()
        else:
            st.info("Click anywhere on the map to add your starting point.")

    # ── Battery sliders ──
    st.markdown('<div class="section-label">🔋 Battery</div>',
                unsafe_allow_html=True)
    col_b1, col_b2 = st.columns(2)
    with col_b1:
        battery_start = st.slider("Start %", 0, 100, 85, 5,
                                  help="Current battery level")
    with col_b2:
        battery_end = st.slider("End Min %", 0, 100, 20, 5,
                                help="Minimum SOC at final destination")

    # ── Priority weights (always visible) ──
    st.markdown('<div class="section-label">⚖️ Priority Weights</div>',
                unsafe_allow_html=True)
    st.caption("1 = Low  •  5 = Critical")
    ac1, ac2, ac3 = st.columns(3)
    with ac1:
        w_time = st.slider("⏱ Time", 1, 5, 3, key="w_time")
    with ac2:
        w_cost = st.slider("💰 Cost", 1, 5, 3, key="w_cost")
    with ac3:
        w_anxiety = st.slider("😰 Anxiety", 1, 5, 3, key="w_anxiety")

    # ── Battery en-route limits (always visible) ──
    st.markdown('<div class="section-label">🛡️ Battery Limits (en-route)</div>',
                unsafe_allow_html=True)
    bl1, bl2 = st.columns(2)
    with bl1:
        battery_floor = st.slider("Floor %", 0, 100, 0, 5,
                                  help="Never drop below this SOC during travel")
    with bl2:
        battery_ceil = st.slider("Ceiling %", 0, 100, 100, 5,
                                 help="Never charge above this SOC during travel")

    # ── Advanced Settings (only seeds) ──
    with st.expander("⚙️ Advanced Settings", expanded=False):
        st.markdown("**Simulation Seeds**")
        sd1, sd2 = st.columns(2)
        with sd1:
            weather_seed = st.number_input("🌦 Weather Seed", value=42,
                                           min_value=0, step=1)
        with sd2:
            occupancy_seed = st.number_input("🏗 Occupancy Seed", value=0,
                                             min_value=0, step=1)

    # ── Divider before button ──
    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

    # ── Plan button ──
    plan_clicked = st.button("⚡ Plan My Route", type="primary",
                             width='stretch')

    # ── Execution ──
    if plan_clicked:
        waypoint_coords = None
        if input_mode == "🗺️ Map Mode":
            if len(st.session_state.map_waypoints) < 2:
                st.error("⚠️ Please select at least a Source and one Destination on the map.")
                return
            source_clean = st.session_state.map_waypoints[0]["label"]
            dest_lines = [wp["label"] for wp in st.session_state.map_waypoints[1:]]
            waypoint_coords = [(wp["lat"], wp["lon"]) for wp in st.session_state.map_waypoints]
        else:
            source_clean = source.strip()
            dest_lines = [d.strip() for d in destinations_raw.strip().splitlines()
                          if d.strip()]

        if not source_clean:
            st.error("⚠️ Please enter a source location.")
            return
        if not dest_lines:
            st.error("⚠️ Please enter at least one destination.")
            return

        st.markdown('<div class="section-label">🔄 Running evolutionary optimizer…</div>', unsafe_allow_html=True)
        log_placeholder = st.empty()
        
        # Start capturing stdout for the log panel
        log_capture = LogCapture(log_placeholder)
        log_capture.start()
        log_text = ""

        with st.spinner("Processing..."):
            try:
                # Load vehicle
                vehicle = find_vehicle_by_id(selected_car_id)

                # Build preferences
                prefs = UserPreferences(
                    source=source_clean,
                    destinations=dest_lines,
                    battery_start_pct=float(battery_start),
                    battery_end_min_pct=float(battery_end),
                    battery_capacity_kwh=vehicle.battery_kwh,
                    consumption_kwh_per_100km=vehicle.consumption_kwh_per_100km,
                    range_km=vehicle.range_km,
                    priority_time=w_time,
                    priority_cost=w_cost,
                    priority_anxiety=w_anxiety,
                    battery_min_enroute_pct=float(battery_floor),
                    battery_max_enroute_pct=float(battery_ceil),
                )

                # Set occupancy seed
                set_occupancy_seed(occupancy_seed)

                # Run the pipeline (live_traffic hardcoded to False)
                result = plan_journey(prefs, live_traffic=False,
                                      weather_seed=weather_seed,
                                      waypoint_coords=waypoint_coords)

                # Stop capturing
                log_capture.stop()
                log_text = log_capture.getvalue()
                log_placeholder.empty() # Clear the live logs

                # Generate plots
                map_buf = generate_map_image(result)
                conv_buf = generate_convergence_image(result)

                # Save to history
                save_to_history(result, map_buf, conv_buf, log_text=log_text)

                # Reset buffers for display
                map_buf.seek(0)
                conv_buf.seek(0)

            except Exception as e:
                log_capture.stop()
                log_text = log_capture.getvalue()
                st.error(f"❌ Planning failed: {e}")
                import traceback
                with st.expander("🔍 Error Details", expanded=True):
                    st.code(traceback.format_exc())
                if log_text:
                    with st.expander("📋 Pipeline Logs (at time of error)", expanded=True):
                        st.code(log_text, language="text")
                return

        # ── Render results ──
        render_results(result, map_buf, conv_buf, log_text=log_text)

    # ── Show last result from history if no new run ──
    elif st.session_state.plot_history:
        last = st.session_state.plot_history[0]
        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="section-label">📌 Last Run — {last["itinerary"]}'
            f' ({last["timestamp"]})</div>',
            unsafe_allow_html=True,
        )

        # Reconstruct buffers from cached bytes
        map_buf = io.BytesIO(last["map_png"])
        conv_buf = io.BytesIO(last["conv_png"])

        # Render a lightweight version of results from cached data
        total_hrs = last["total_time_min"] / 60
        time_str = (f"{int(total_hrs)}h {int(last['total_time_min'] % 60)}m"
                    if total_hrs >= 1 else f"{last['total_time_min']:.0f} min")

        st.markdown(
            f"""
            <div class="metric-row">
                <div class="metric-card">
                    <div class="metric-icon">🕐</div>
                    <div class="metric-value">{time_str}</div>
                    <div class="metric-label">Total Time</div>
                </div>
                <div class="metric-card">
                    <div class="metric-icon">💰</div>
                    <div class="metric-value">{last['total_cost']:.0f} TL</div>
                    <div class="metric-label">Cost</div>
                </div>
                <div class="metric-card">
                    <div class="metric-icon">📊</div>
                    <div class="metric-value">{last['total_z_score']:.2f}</div>
                    <div class="metric-label">Z-Score</div>
                </div>
                <div class="metric-card">
                    <div class="metric-icon">🔋</div>
                    <div class="metric-value">{last['battery_end']:.0f}%</div>
                    <div class="metric-label">Final SOC</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown('<div class="map-container">', unsafe_allow_html=True)
        st.image(map_buf, width='stretch')
        st.markdown('</div>', unsafe_allow_html=True)

        with st.expander("📈 Algorithm Convergence", expanded=False):
            st.image(conv_buf, caption="Z-score convergence per generation",
                     width='stretch')

        if last.get("log_text"):
            with st.expander("📋 Pipeline Logs", expanded=False):
                st.code(last["log_text"], language="text")


if __name__ == "__main__":
    main()
