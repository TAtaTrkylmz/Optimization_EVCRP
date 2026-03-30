"""
Read data/geocoded_epdk_data_partial.csv and export rows whose Latitude/Longitude are still missing.

Writes data/epdk_ungeocoded_rows.csv and data/epdk_ungeocoded_addresses.csv (unique Adres).
Use before another geocoding pass. For day-to-day analysis, prefer util/export_epdk_geocoding_split.py
(data/geocoded_epdk_data.csv + data/epdk_missing_geocoding.csv).
"""
import os
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"

PARTIAL_FILE = DATA_DIR / "geocoded_epdk_data_partial.csv"
ADDRESS_COLUMN = "Adres"
ROWS_OUTPUT = DATA_DIR / "epdk_ungeocoded_rows.csv"
UNIQUE_ADDRESSES_OUTPUT = DATA_DIR / "epdk_ungeocoded_addresses.csv"


def main():
    if not os.path.isfile(PARTIAL_FILE):
        print(
            f"Missing {PARTIAL_FILE}. Run `python api/geocode_osm.py` from the repo root first "
            "(or point PARTIAL_FILE to your partial CSV)."
        )
        raise SystemExit(1)

    df = pd.read_csv(PARTIAL_FILE)
    for col in (ADDRESS_COLUMN, "Latitude", "Longitude"):
        if col not in df.columns:
            print(f"Expected column '{col}' in {PARTIAL_FILE}.")
            raise SystemExit(1)

    missing = df["Latitude"].isna() | df["Longitude"].isna()
    df_miss = df.loc[missing].copy()
    n_rows = len(df_miss)
    if n_rows == 0:
        print("No rows without coordinates — nothing to export.")
        return

    addrs = (
        df_miss[ADDRESS_COLUMN]
        .dropna()
        .astype(str)
        .str.strip()
    )
    addrs = addrs[addrs != ""]
    unique_n = addrs.nunique()

    df_miss.to_csv(ROWS_OUTPUT, index=False)
    pd.DataFrame({ADDRESS_COLUMN: addrs.unique()}).to_csv(
        UNIQUE_ADDRESSES_OUTPUT, index=False
    )

    print(
        f"Wrote {n_rows} socket rows ({unique_n} unique addresses) missing coords.\n"
        f"  - {ROWS_OUTPUT}\n"
        f"  - {UNIQUE_ADDRESSES_OUTPUT}"
    )


if __name__ == "__main__":
    main()
