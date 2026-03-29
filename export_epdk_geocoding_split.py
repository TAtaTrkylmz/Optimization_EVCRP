"""
Split geocoded_epdk_data_partial.csv into:
  - geocoded_epdk_data.csv       — rows with both Latitude and Longitude
  - epdk_missing_geocoding.csv   — rows still missing either coordinate

Run after updating the partial file. For a future Google pass on leftovers, either rerun
extract_ungeocoded.py (reads the partial) or build a unique-address list from
epdk_missing_geocoding.csv.
"""
import csv
import os
import sys

PARTIAL_FILE = "geocoded_epdk_data_partial.csv"
OUT_GEOCODED = "geocoded_epdk_data.csv"
OUT_MISSING = "epdk_missing_geocoding.csv"


def _cell_float(s):
    if s is None or str(s).strip() == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def main():
    if not os.path.isfile(PARTIAL_FILE):
        print(f"Missing {PARTIAL_FILE}.")
        sys.exit(1)

    with open(PARTIAL_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            print(f"Empty or invalid CSV: {PARTIAL_FILE}")
            sys.exit(1)
        fieldnames = list(reader.fieldnames)
        if "Latitude" not in fieldnames or "Longitude" not in fieldnames:
            print(f"Expected Latitude and Longitude columns in {PARTIAL_FILE}.")
            sys.exit(1)

        rows_geo = []
        rows_miss = []
        for row in reader:
            lat = _cell_float(row.get("Latitude"))
            lon = _cell_float(row.get("Longitude"))
            if lat is not None and lon is not None:
                rows_geo.append(row)
            else:
                rows_miss.append(row)

    def write_csv(path, rows):
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)

    write_csv(OUT_GEOCODED, rows_geo)
    write_csv(OUT_MISSING, rows_miss)

    n = len(rows_geo) + len(rows_miss)
    print(
        f"Wrote {len(rows_geo)} rows -> {OUT_GEOCODED}\n"
        f"Wrote {len(rows_miss)} rows -> {OUT_MISSING}\n"
        f"(from {n} data rows in {PARTIAL_FILE})"
    )


if __name__ == "__main__":
    main()
