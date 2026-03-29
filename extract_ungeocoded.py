"""
Read geocoded_epdk_data_partial.csv and export rows whose Latitude/Longitude are still missing.

Writes epdk_ungeocoded_rows.csv and epdk_ungeocoded_addresses.csv (unique Adres).
Use before another geocoding pass. For day-to-day analysis, prefer export_epdk_geocoding_split.py
(geocoded_epdk_data.csv + epdk_missing_geocoding.csv).
"""
import os

import pandas as pd

PARTIAL_FILE = "geocoded_epdk_data_partial.csv"
ADDRESS_COLUMN = "Adres"
ROWS_OUTPUT = "epdk_ungeocoded_rows.csv"
UNIQUE_ADDRESSES_OUTPUT = "epdk_ungeocoded_addresses.csv"


def main():
    if not os.path.isfile(PARTIAL_FILE):
        print(f"Missing {PARTIAL_FILE}. Run geocode_osm.py first (or point PARTIAL_FILE to your partial CSV).")
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
