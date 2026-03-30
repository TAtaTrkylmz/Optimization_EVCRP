import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"

# --- 1. CONFIGURATION ---
INPUT_FILE = DATA_DIR / "epdk_data.csv"
OUTPUT_FILE = DATA_DIR / "geocoded_epdk_data.csv"
# Unique-address cache: resume skips rows already present (success or recorded failure).
CHECKPOINT_FILE = DATA_DIR / "geocoded_epdk_checkpoint.csv"
# Full input rows merged with whatever coords are known so far (includes NaN where pending).
PARTIAL_OUTPUT_FILE = DATA_DIR / "geocoded_epdk_data_partial.csv"
ADDRESS_COLUMN = "Adres"
# How often to flush checkpoint + partial CSV (1 = every geocode; higher = less disk I/O).
SAVE_EVERY = 10

# Nominatim REQUIRES a custom User-Agent. Replace with your own email/app name.
HEADERS = {
    "User-Agent": "Optimization_EVCRP(yusufzeybek@std.iyte.edu.tr)"
}


def get_coordinates_osm(address):
    """Hits the Nominatim API and returns (lat, lon)."""
    if pd.isna(address) or str(address).strip() == "":
        return None, None

    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": address,
        "format": "json",
        "limit": 1,
        "countrycodes": "tr",
    }

    try:
        response = requests.get(url, params=params, headers=HEADERS, timeout=60)
        response.raise_for_status()
        data = response.json()

        if data and len(data) > 0:
            return float(data[0]["lat"]), float(data[0]["lon"])
        return None, None

    except requests.exceptions.RequestException as e:
        print(f"Network error for address '{address}': {e}")
        return None, None


def load_checkpoint(path):
    """Returns dict address -> (lat, lon); failed lookups stored as (None, None)."""
    if not os.path.isfile(path):
        return {}
    ck = pd.read_csv(path)
    if ADDRESS_COLUMN not in ck.columns:
        print(f"Warning: {path} missing '{ADDRESS_COLUMN}'; ignoring checkpoint.")
        return {}
    out = {}
    for _, row in ck.iterrows():
        addr = row[ADDRESS_COLUMN]
        lat, lon = row.get("Latitude"), row.get("Longitude")
        if pd.isna(lat) or pd.isna(lon):
            out[addr] = (None, None)
        else:
            out[addr] = (float(lat), float(lon))
    return out


def save_progress(df_source, address_coords, checkpoint_path, partial_path):
    """Write unique-address checkpoint and full-row partial merge."""
    rows = [(addr, coords[0], coords[1]) for addr, coords in address_coords.items()]
    ck_df = pd.DataFrame(rows, columns=[ADDRESS_COLUMN, "Latitude", "Longitude"])
    ck_df.to_csv(checkpoint_path, index=False)

    coords_df = pd.DataFrame.from_dict(
        address_coords, orient="index", columns=["Latitude", "Longitude"]
    )
    coords_df.index.name = ADDRESS_COLUMN
    coords_df = coords_df.reset_index()
    df_partial = pd.merge(df_source, coords_df, on=ADDRESS_COLUMN, how="left")
    df_partial.to_csv(partial_path, index=False)


def finalize_clean_output(df_source, address_coords, output_path):
    """Same as before: full merge, then drop rows without coordinates."""
    coords_df = pd.DataFrame.from_dict(
        address_coords, orient="index", columns=["Latitude", "Longitude"]
    )
    coords_df.index.name = ADDRESS_COLUMN
    coords_df = coords_df.reset_index()
    df_final = pd.merge(df_source, coords_df, on=ADDRESS_COLUMN, how="left")
    df_clean = df_final.dropna(subset=["Latitude", "Longitude"])
    df_clean.to_csv(output_path, index=False)
    return df_final, df_clean


# --- 2. LOAD DATA ---
print(f"Loading {INPUT_FILE}...")
df = pd.read_csv(INPUT_FILE)

# --- 3. EXTRACT UNIQUE ADDRESSES ---
unique_addresses = df[ADDRESS_COLUMN].dropna().unique()
total_unique = len(unique_addresses)

address_coords = load_checkpoint(CHECKPOINT_FILE)
already = len(address_coords)
to_do = sum(1 for a in unique_addresses if a not in address_coords)

print(f"Found {len(df)} total rows, {total_unique} unique addresses.")
if already:
    print(
        f"Checkpoint: {already} unique addresses loaded from {CHECKPOINT_FILE}; "
        f"{to_do} remaining."
    )
print("Starting OpenStreetMap geocoding...\n")
print("Nominatim limit: ~1 request/second. Progress is saved every "
      f"{SAVE_EVERY} geocodes to {CHECKPOINT_FILE} and {PARTIAL_OUTPUT_FILE}.")
print("You can interrupt (Ctrl+C); rerun the script to resume.\n")

processed_since_save = 0
new_geocodes = 0

try:
    for index, address in enumerate(unique_addresses):
        if address in address_coords:
            continue

        lat, lon = get_coordinates_osm(address)
        address_coords[address] = (lat, lon)
        new_geocodes += 1
        processed_since_save += 1

        if new_geocodes % 10 == 0:
            done_unique = len(address_coords)
            print(f"Geocoded {done_unique}/{total_unique} unique addresses...")

        if processed_since_save >= SAVE_EVERY:
            save_progress(df, address_coords, CHECKPOINT_FILE, PARTIAL_OUTPUT_FILE)
            processed_since_save = 0

        time.sleep(1.1)

except KeyboardInterrupt:
    print("\nInterrupted — writing checkpoint and partial output...")
    save_progress(df, address_coords, CHECKPOINT_FILE, PARTIAL_OUTPUT_FILE)
    print(f"Saved {CHECKPOINT_FILE} ({len(address_coords)} unique addresses).")
    print(f"Saved {PARTIAL_OUTPUT_FILE} (all input rows; NaN where not yet geocoded).")
    sys.exit(130)

# Flush any remaining progress not yet written
if processed_since_save > 0:
    save_progress(df, address_coords, CHECKPOINT_FILE, PARTIAL_OUTPUT_FILE)

# --- 5–6. FINAL OUTPUT ---
print("\nMapping coordinates back to all sockets...")
df_final, df_clean = finalize_clean_output(df, address_coords, OUTPUT_FILE)

print(f"\nSuccess! Saved {len(df_clean)} geocoded sockets to {OUTPUT_FILE}.")
print(f"Failed to geocode {len(df) - len(df_clean)} sockets (addresses might be too vague for OSM).")
print(f"Checkpoint: {CHECKPOINT_FILE}; partial merge: {PARTIAL_OUTPUT_FILE}.")
