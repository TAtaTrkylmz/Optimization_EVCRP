"""
SQLite-based caching for real-world distances, travel times, and route geometry
between geographic coordinates.
"""
import json
import sqlite3
from pathlib import Path

# The cache file lives in the data/ directory.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = REPO_ROOT / "data" / "route_cache.db"

def _get_connection() -> sqlite3.Connection:
    """Returns a connection to the SQLite cache, creating the table if needed."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS route_cache (
            lat_o REAL,
            lon_o REAL,
            lat_d REAL,
            lon_d REAL,
            road_km REAL,
            drive_min REAL,
            PRIMARY KEY (lat_o, lon_o, lat_d, lon_d)
        )
        """
    )
    # Add geometry column if it doesn't exist (migration for existing DBs)
    try:
        conn.execute("ALTER TABLE route_cache ADD COLUMN geometry TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS geocode_cache (
            query TEXT PRIMARY KEY,
            lat REAL,
            lon REAL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reverse_geocode_cache (
            lat REAL,
            lon REAL,
            label TEXT,
            PRIMARY KEY (lat, lon)
        )
        """
    )
    conn.commit()
    return conn

def _round_coord(coord: float) -> float:
    """Round coordinates to 4 decimals (~11m precision) to maximize cache hits."""
    return round(coord, 4)

def get_route_from_cache(lat_o: float, lon_o: float, lat_d: float, lon_d: float) -> tuple[float, float] | None:
    """
    Check if the route between origin and destination is cached.
    Returns (road_km, drive_min) if found, otherwise None.
    """
    lo, lno = _round_coord(lat_o), _round_coord(lon_o)
    ld, lnd = _round_coord(lat_d), _round_coord(lon_d)
    
    with _get_connection() as conn:
        cursor = conn.execute(
            "SELECT road_km, drive_min FROM route_cache WHERE lat_o=? AND lon_o=? AND lat_d=? AND lon_d=?",
            (lo, lno, ld, lnd)
        )
        row = cursor.fetchone()
        if row:
            return float(row[0]), float(row[1])
        
        # Check reverse direction as an approximation if direct is missing
        cursor = conn.execute(
            "SELECT road_km, drive_min FROM route_cache WHERE lat_o=? AND lon_o=? AND lat_d=? AND lon_d=?",
            (ld, lnd, lo, lno)
        )
        row = cursor.fetchone()
        if row:
            return float(row[0]), float(row[1])
            
    return None

def get_geometry_from_cache(lat_o: float, lon_o: float, lat_d: float, lon_d: float) -> list[tuple[float, float]] | None:
    """
    Get cached route geometry (polyline) between two points.
    Returns list of (lat, lon) tuples, or None if not cached.
    """
    lo, lno = _round_coord(lat_o), _round_coord(lon_o)
    ld, lnd = _round_coord(lat_d), _round_coord(lon_d)
    
    with _get_connection() as conn:
        cursor = conn.execute(
            "SELECT geometry FROM route_cache WHERE lat_o=? AND lon_o=? AND lat_d=? AND lon_d=?",
            (lo, lno, ld, lnd)
        )
        row = cursor.fetchone()
        if row and row[0]:
            return json.loads(row[0])
        
        # Check reverse — reverse the points
        cursor = conn.execute(
            "SELECT geometry FROM route_cache WHERE lat_o=? AND lon_o=? AND lat_d=? AND lon_d=?",
            (ld, lnd, lo, lno)
        )
        row = cursor.fetchone()
        if row and row[0]:
            pts = json.loads(row[0])
            return list(reversed(pts))
    return None

def save_geometry_to_cache(lat_o: float, lon_o: float, lat_d: float, lon_d: float, 
                           geometry: list[tuple[float, float]]) -> None:
    """Save route geometry into an existing route_cache row."""
    lo, lno = _round_coord(lat_o), _round_coord(lon_o)
    ld, lnd = _round_coord(lat_d), _round_coord(lon_d)
    geo_json = json.dumps(geometry)
    
    with _get_connection() as conn:
        conn.execute(
            "UPDATE route_cache SET geometry=? WHERE lat_o=? AND lon_o=? AND lat_d=? AND lon_d=?",
            (geo_json, lo, lno, ld, lnd)
        )
        conn.commit()

def load_routes_bulk(coords: list[tuple[float, float]]) -> dict[tuple[float, float, float, float], tuple[float, float]]:
    """Load ALL cached routes relevant to a node list in ONE DB connection.

    Returns a dict keyed by (rounded lat_o, lon_o, lat_d, lon_d) -> (road_km, drive_min).
    """
    result = {}
    
    with _get_connection() as conn:
        cursor = conn.execute("SELECT lat_o, lon_o, lat_d, lon_d, road_km, drive_min FROM route_cache")
        for row in cursor.fetchall():
            key = (row[0], row[1], row[2], row[3])
            result[key] = (float(row[4]), float(row[5]))
            # Also store reverse direction
            rev_key = (row[2], row[3], row[0], row[1])
            if rev_key not in result:
                result[rev_key] = (float(row[4]), float(row[5]))
    return result

def save_route_to_cache(lat_o: float, lon_o: float, lat_d: float, lon_d: float, 
                        road_km: float, drive_min: float,
                        geometry: list[tuple[float, float]] | None = None) -> None:
    """
    Save the route information into the SQLite cache.
    """
    lo, lno = _round_coord(lat_o), _round_coord(lon_o)
    ld, lnd = _round_coord(lat_d), _round_coord(lon_d)
    geo_json = json.dumps(geometry) if geometry else None
    
    with _get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO route_cache (lat_o, lon_o, lat_d, lon_d, road_km, drive_min, geometry)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (lo, lno, ld, lnd, road_km, drive_min, geo_json)
        )
        conn.commit()

def get_geocode_from_cache(query: str) -> tuple[float, float] | None:
    """Retrieve geocoded coordinates from the cache."""
    with _get_connection() as conn:
        cursor = conn.execute("SELECT lat, lon FROM geocode_cache WHERE query=?", (query.strip().lower(),))
        row = cursor.fetchone()
        return (float(row[0]), float(row[1])) if row else None

def save_geocode_to_cache(query: str, lat: float, lon: float) -> None:
    """Save geocoded coordinates to the cache."""
    with _get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO geocode_cache (query, lat, lon) VALUES (?, ?, ?)", 
            (query.strip().lower(), lat, lon)
        )
        conn.commit()

def get_reverse_geocode_from_cache(lat: float, lon: float) -> str | None:
    """Retrieve reverse geocoded label from the cache."""
    r_lat, r_lon = _round_coord(lat), _round_coord(lon)
    with _get_connection() as conn:
        cursor = conn.execute("SELECT label FROM reverse_geocode_cache WHERE lat=? AND lon=?", (r_lat, r_lon))
        row = cursor.fetchone()
        return str(row[0]) if row else None

def save_reverse_geocode_to_cache(lat: float, lon: float, label: str) -> None:
    """Save reverse geocoded label to the cache."""
    r_lat, r_lon = _round_coord(lat), _round_coord(lon)
    with _get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO reverse_geocode_cache (lat, lon, label) VALUES (?, ?, ?)", 
            (r_lat, r_lon, label.strip())
        )
        conn.commit()
