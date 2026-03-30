"""
Second-pass geocoding with Google Geocoding API for addresses still empty after Nominatim.

Typical reasons rows are still empty: OSM had no hit, or you stopped early (quota / cap /
interrupt). Google is not implied to be “worse” — free-tier quota often ends the run before
every address is tried.

Flow: run util/extract_ungeocoded.py first, then this script.

Reads data/epdk_ungeocoded_addresses.csv, maintains a Google-specific checkpoint, merges into
data/geocoded_epdk_data_partial.csv and refreshes data/geocoded_epdk_data.csv.

Each distinct address is queried at most once: unique input + checkpoint skips retries.
"""
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"

# --- CONFIGURATION ---
UNIQUE_ADDRESSES_FILE = DATA_DIR / "epdk_ungeocoded_addresses.csv"
PARTIAL_FILE = DATA_DIR / "geocoded_epdk_data_partial.csv"
OUTPUT_FILE = DATA_DIR / "geocoded_epdk_data.csv"
CHECKPOINT_FILE = DATA_DIR / "geocoded_google_checkpoint.csv"
ADDRESS_COLUMN = "Adres"
SAVE_EVERY = 10
# Seconds between requests (tune for your Google Cloud quota).
SLEEP_SEC = 0.05
# Max NEW Geocoding API requests this process will make (then save and exit; rerun to continue).
MAX_API_CALLS_PER_RUN = 1000

GOOGLE_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"


def load_env_dotenv(path=None):
    """Set os.environ from KEY=value lines if .env exists (no extra dependency)."""
    p = Path(path) if path is not None else REPO_ROOT / ".env"
    if not p.is_file():
        return
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            os.environ.setdefault(key, val)


def get_api_key():
    load_env_dotenv()
    key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if not key:
        print(
            "Set GOOGLE_MAPS_API_KEY in the environment or in .env\n"
            "Example: export GOOGLE_MAPS_API_KEY=your_key"
        )
        sys.exit(1)
    return key


def get_coordinates_google(address, api_key):
    """Call Geocoding API; return (lat, lon) or (None, None)."""
    if pd.isna(address) or str(address).strip() == "":
        return None, None

    params = {
        "address": str(address).strip(),
        "key": api_key,
        "region": "tr",
    }

    try:
        response = requests.get(GOOGLE_GEOCODE_URL, params=params, timeout=60)
        response.raise_for_status()
        payload = response.json()
    except requests.exceptions.RequestException as e:
        print(f"Network error for address '{address}': {e}")
        return None, None

    status = payload.get("status")
    if status == "OK" and payload.get("results"):
        loc = payload["results"][0]["geometry"]["location"]
        return float(loc["lat"]), float(loc["lng"])

    if status not in ("ZERO_RESULTS",):
        print(f"Google Geocoding status={status} for '{address}': {payload.get('error_message', '')}")

    return None, None


def load_checkpoint(path):
    """address -> (lat, lon); failed lookups as (None, None)."""
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


def save_google_checkpoint(address_coords, checkpoint_path):
    rows = [(addr, coords[0], coords[1]) for addr, coords in address_coords.items()]
    pd.DataFrame(rows, columns=[ADDRESS_COLUMN, "Latitude", "Longitude"]).to_csv(
        checkpoint_path, index=False
    )


def apply_google_to_partial(df_partial, google_coords):
    """Fill NaN Latitude/Longitude where Google has a successful hit."""
    df = df_partial.copy()
    mask = df["Latitude"].isna() | df["Longitude"].isna()
    for idx in df.index[mask]:
        addr = df.at[idx, ADDRESS_COLUMN]
        if addr not in google_coords:
            continue
        lat, lon = google_coords[addr]
        if lat is not None and lon is not None:
            df.at[idx, "Latitude"] = lat
            df.at[idx, "Longitude"] = lon
    return df


def main():
    api_key = get_api_key()

    if not os.path.isfile(UNIQUE_ADDRESSES_FILE):
        print(
            f"Missing {UNIQUE_ADDRESSES_FILE}.\n"
            "Run: python util/extract_ungeocoded.py (from the repo root)"
        )
        sys.exit(1)
    if not os.path.isfile(PARTIAL_FILE):
        print(f"Missing {PARTIAL_FILE}.")
        sys.exit(1)

    addr_df = pd.read_csv(UNIQUE_ADDRESSES_FILE)
    if ADDRESS_COLUMN not in addr_df.columns:
        print(f"{UNIQUE_ADDRESSES_FILE} must have a column '{ADDRESS_COLUMN}'.")
        sys.exit(1)

    unique_addresses = (
        addr_df[ADDRESS_COLUMN]
        .dropna()
        .astype(str)
        .str.strip()
    )
    unique_addresses = unique_addresses[unique_addresses != ""].unique()
    total_unique = len(unique_addresses)

    address_coords = load_checkpoint(CHECKPOINT_FILE)
    already = len(address_coords)
    to_do = sum(1 for a in unique_addresses if a not in address_coords)

    print(f"Google pass: {total_unique} unique addresses in {UNIQUE_ADDRESSES_FILE}.")
    if already:
        print(
            f"Checkpoint: {already} loaded from {CHECKPOINT_FILE}; "
            f"{to_do} remaining."
        )
    print(
        f"Progress saved every {SAVE_EVERY} geocodes to {CHECKPOINT_FILE}.\n"
        f"Partial merge updated on each save and at end -> {PARTIAL_FILE}\n"
        f"Cap: at most {MAX_API_CALLS_PER_RUN} new API calls per run (rerun to process the rest).\n"
    )

    df_partial = pd.read_csv(PARTIAL_FILE)
    processed_since_save = 0
    new_geocodes = 0
    api_calls_this_run = 0
    stopped_for_limit = False

    try:
        for address in unique_addresses:
            if address in address_coords:
                continue

            if api_calls_this_run >= MAX_API_CALLS_PER_RUN:
                stopped_for_limit = True
                print(
                    f"\nStopped at {MAX_API_CALLS_PER_RUN} API calls this run. "
                    "Checkpoint saved; rerun the script to continue."
                )
                break

            lat, lon = get_coordinates_google(address, api_key)
            api_calls_this_run += 1
            address_coords[address] = (lat, lon)
            new_geocodes += 1
            processed_since_save += 1

            if new_geocodes % 10 == 0:
                done_batch = sum(1 for a in unique_addresses if a in address_coords)
                print(f"Tried {done_batch}/{total_unique} unique addresses (checkpoint size {len(address_coords)})...")

            if processed_since_save >= SAVE_EVERY:
                save_google_checkpoint(address_coords, CHECKPOINT_FILE)
                updated = apply_google_to_partial(df_partial, address_coords)
                updated.to_csv(PARTIAL_FILE, index=False)
                processed_since_save = 0

            if SLEEP_SEC > 0:
                time.sleep(SLEEP_SEC)

    except KeyboardInterrupt:
        print("\nInterrupted — writing checkpoint and partial...")
        save_google_checkpoint(address_coords, CHECKPOINT_FILE)
        apply_google_to_partial(df_partial, address_coords).to_csv(PARTIAL_FILE, index=False)
        print(f"Saved {CHECKPOINT_FILE} ({len(address_coords)} addresses).")
        sys.exit(130)

    if processed_since_save > 0:
        save_google_checkpoint(address_coords, CHECKPOINT_FILE)

    df_updated = apply_google_to_partial(df_partial, address_coords)
    df_updated.to_csv(PARTIAL_FILE, index=False)

    df_clean = df_updated.dropna(subset=["Latitude", "Longitude"])
    df_clean.to_csv(OUTPUT_FILE, index=False)

    still_missing = len(df_updated) - len(df_clean)
    remaining_unique = sum(1 for a in unique_addresses if a not in address_coords)
    tail = (
        f"\n{remaining_unique} unique addresses not yet in checkpoint — rerun to continue."
        if stopped_for_limit or remaining_unique
        else ""
    )
    status = "Stopped (call limit)." if stopped_for_limit else "Done."
    print(
        f"\n{status} Wrote {len(df_clean)} fully geocoded rows to {OUTPUT_FILE}.\n"
        f"Still missing coords: {still_missing} socket rows.\n"
        f"Checkpoint: {CHECKPOINT_FILE}; partial: {PARTIAL_FILE}.{tail}"
    )


if __name__ == "__main__":
    main()
