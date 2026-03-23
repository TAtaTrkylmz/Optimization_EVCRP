import pandas as pd
import requests
import time

# --- 1. CONFIGURATION ---
INPUT_FILE = "epdk_data.csv"
OUTPUT_FILE = "geocoded_epdk_data.csv"
ADDRESS_COLUMN = "Adres"

# Nominatim REQUIRES a custom User-Agent. Replace with your own email/app name.
HEADERS = {
    "User-Agent": "Optimization_EVRP(yusufz27x@gmail.com)"
}

def get_coordinates_osm(address):
    """Hits the Nominatim API and returns (lat, lon)."""
    if pd.isna(address) or str(address).strip() == "":
        return None, None

    # Nominatim search endpoint
    url = "https://nominatim.openstreetmap.org/search"
    
    # Parameters for the request
    params = {
        'q': address,
        'format': 'json',
        'limit': 1,           # We only need the top result
        'countrycodes': 'tr'  # Restrict search to Turkey for better accuracy
    }

    try:
        response = requests.get(url, params=params, headers=HEADERS)
        response.raise_for_status()
        data = response.json()

        if data and len(data) > 0:
            # Nominatim returns lat/lon as strings, so we convert them to floats
            return float(data[0]['lat']), float(data[0]['lon'])
        else:
            return None, None
            
    except requests.exceptions.RequestException as e:
        print(f"Network error for address '{address}': {e}")
        return None, None

# --- 2. LOAD DATA ---
print(f"Loading {INPUT_FILE}...")
df = pd.read_csv(INPUT_FILE)

# --- 3. EXTRACT UNIQUE ADDRESSES ---
unique_addresses = df[ADDRESS_COLUMN].dropna().unique()
total_unique = len(unique_addresses)

print(f"Found {len(df)} total rows, but only {total_unique} unique addresses.")
print("Starting OpenStreetMap geocoding process...\n")
print("⚠️ WARNING: Nominatim enforces a strict 1 request/second limit.")
print("This will take approximately 4 hours. Do not stop the script!\n")

# --- 4. GEOCODE UNIQUE ADDRESSES ---
address_coords = {}

for index, address in enumerate(unique_addresses):
    lat, lon = get_coordinates_osm(address)
    address_coords[address] = (lat, lon)
    
    # Print progress
    if (index + 1) % 10 == 0:
        print(f"Processed {index + 1}/{total_unique} addresses...")
        
    # CRITICAL: Sleep for at least 1 second to avoid getting IP banned by OSM
    time.sleep(1.1) 

# --- 5. MAP COORDINATES BACK TO THE MAIN DATASET ---
print("\nMapping coordinates back to all sockets...")
coords_df = pd.DataFrame.from_dict(address_coords, orient='index', columns=['Latitude', 'Longitude'])
coords_df.index.name = ADDRESS_COLUMN
coords_df.reset_index(inplace=True)

# Merge back onto the original dataframe
df_final = pd.merge(df, coords_df, on=ADDRESS_COLUMN, how='left')

# --- 6. SAVE RESULTS ---
# Drop rows where coordinates couldn't be found
df_clean = df_final.dropna(subset=['Latitude', 'Longitude'])

df_clean.to_csv(OUTPUT_FILE, index=False)
print(f"\nSuccess! Saved {len(df_clean)} geocoded sockets to {OUTPUT_FILE}.")
print(f"Failed to geocode {len(df) - len(df_clean)} sockets (addresses might be too vague for OSM).")