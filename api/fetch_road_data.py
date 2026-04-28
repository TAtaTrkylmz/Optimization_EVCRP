import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from planner.setup.config import UserPreferences
from planner.setup.tomtom import load_api_key, geocode, route_summary
from planner.setup.stations import load_stations, filter_corridor, build_node_list

def main():
    parser = argparse.ArgumentParser(description="Pre-fetch and cache real-world road data for a given corridor.")
    parser.add_argument("--source", required=True, help="Origin location, e.g. 'Izmir Center, Turkey'")
    parser.add_argument("--destinations", required=True, nargs="+", help="Destination(s)")
    parser.add_argument("--delay", type=float, default=0.25, help="Delay between API calls in seconds (default 0.25)")
    args = parser.parse_args()
    
    api_key = load_api_key()
    stations = load_stations()
    
    waypoints = [args.source] + args.destinations
    print(f"Geocoding {len(waypoints)} waypoints...")
    coords = []
    for wp in waypoints:
        lat, lon = geocode(wp, api_key)
        coords.append((lat, lon))
        print(f"  {wp}: {lat:.5f}, {lon:.5f}")
        
    print("\nStarting fetch loop...")
    
    for i in range(len(coords) - 1):
        lat_o, lon_o = coords[i]
        lat_d, lon_d = coords[i+1]
        
        print(f"\nLeg {i+1}: {waypoints[i]} -> {waypoints[i+1]}")
        corridor_df = filter_corridor(stations, lat_o, lon_o, lat_d, lon_d)
        print(f"Discovered {len(corridor_df)} stations in corridor.")
        
        node_coords, _, _ = build_node_list(lat_o, lon_o, lat_d, lon_d, corridor_df)
        n = len(node_coords)
        print(f"Total nodes in matrix: {n} (Origin + Stations + Dest)")
        
        total_pairs = n * (n - 1)
        print(f"Pairs to check: {total_pairs}")
        
        fetched = 0
        cached_count = 0
        from planner.setup.routing_cache import get_route_from_cache
        
        for r_idx in range(n):
            for c_idx in range(n):
                if r_idx == c_idx:
                    continue
                    
                lat1, lon1 = node_coords[r_idx]
                lat2, lon2 = node_coords[c_idx]
                
                # Check cache directly first so we don't delay
                if get_route_from_cache(lat1, lon1, lat2, lon2) is not None:
                    cached_count += 1
                    continue
                    
                # Time to fetch
                try:
                    km, mins = route_summary(lat1, lon1, lat2, lon2, api_key, use_cache=False, live_traffic=False)
                    fetched += 1
                    if fetched % 10 == 0:
                        print(f"  ... fetched {fetched} new routes (cache hits: {cached_count})")
                    time.sleep(args.delay)
                except RuntimeError as e:
                    print(f"\nAPI Error during pair fetch: {e}")
                    print("Stopping fetch process. The cache contains partial data which is safe to use.")
                    sys.exit(1)
                    
        print(f"Leg {i+1} complete. Fetched {fetched} new routes, ignored {cached_count} already in cache.")

if __name__ == "__main__":
    main()
