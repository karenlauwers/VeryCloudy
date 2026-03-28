"""
Post-processing fixes on cloud_gallery_all_info_testset.csv (and later, the full dataset).

Three operations:
1. Rename columns that carry merge suffixes or non-descriptive names.
2. Reverse-geocode rows that have lat/lon but no city/region/country.
3. Fill cloud_type1 from subtype1 when cloud_type1 is missing (per tech_specs §4.4).

Run via: python scripts/main_update.py
"""

import math
import time
from pathlib import Path

import pandas as pd
from geopy.geocoders import Nominatim
from tqdm import tqdm

from verycloudy.config import NOMINATIM_DELAY


# -------------------------
# Step 1 — Column renames
# -------------------------

COLUMN_RENAMES = {
    "date_taken_utc_x": "date_taken_utc_xmp",
    "time_taken_utc_x": "time_taken_utc_xmp",
    "source_field":     "datetime_source",
    "fallback_used":    "fallback_dt_used",
    "error":            "datetime_capture",
}


def fix_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """Rename columns that carry merge suffixes or non-descriptive names."""
    present = {k: v for k, v in COLUMN_RENAMES.items() if k in df.columns}
    if present:
        df = df.rename(columns=present)
        print(f"Renamed {len(present)} column(s): {list(present.keys())}")
    else:
        print("No columns to rename (already clean or not present).")
    return df


# -------------------------
# Step 2 — Reverse geocode
# -------------------------

def _needs_location(row: pd.Series) -> bool:
    """True if lat/lon are valid but at least one of city/region/country is blank."""
    try:
        lat = float(row.get("latitude"))
        lon = float(row.get("longitude"))
    except (TypeError, ValueError):
        return False
    if math.isnan(lat) or math.isnan(lon):
        return False
    city    = str(row.get("city",    "")).strip()
    region  = str(row.get("region",  "")).strip()
    country = str(row.get("country", "")).strip()
    # pandas reads empty cells as float NaN; str(nan) == "nan"
    blank = {"", "nan", "none"}
    return (city.lower() in blank or region.lower() in blank or country.lower() in blank)


def fix_missing_locations(df: pd.DataFrame) -> pd.DataFrame:
    """Reverse geocode rows that have lat/lon but incomplete city/region/country."""
    geolocator = Nominatim(user_agent="verycloudy/1.0 (thesis project)")

    mask = df.apply(_needs_location, axis=1)
    candidates = df[mask].index.tolist()
    print(f"Rows needing reverse geocode: {len(candidates)}")

    updated = 0
    for idx in tqdm(candidates, desc="Reverse geocoding", unit="row"):
        lat = float(df.at[idx, "latitude"])
        lon = float(df.at[idx, "longitude"])
        try:
            location = geolocator.reverse((lat, lon), language="en", timeout=10)
            time.sleep(NOMINATIM_DELAY)
        except Exception as exc:
            print(f"  [ERROR] reverse geocode ({lat},{lon}): {exc}")
            time.sleep(NOMINATIM_DELAY)
            continue

        if location is None:
            continue

        addr = location.raw.get("address", {})
        city    = addr.get("city") or addr.get("town") or addr.get("village") or ""
        region  = addr.get("state", "")
        country = addr.get("country_code", "").upper()  # 2-letter ISO code, e.g. "BE"

        if city or region or country:
            df.at[idx, "city"]            = city    or df.at[idx, "city"]
            df.at[idx, "region"]          = region  or df.at[idx, "region"]
            df.at[idx, "country"]         = country or df.at[idx, "country"]
            df.at[idx, "location_source"] = "reverse_geocode"
            updated += 1

    print(f"Reverse geocoded: {updated} row(s) updated.")
    return df


# -------------------------
# Step 3 — Subtype → cloud_type fix
# -------------------------

SUBTYPE_TO_CLOUDTYPE = {
    "volutus":          "altocumulus",
    "arcus":            "cumulonimbus",
    "radiatus":         "cumulus",
    "cavum":            "altocumulus",
    "mamma":            "cumulonimbus",
    "tuba":             "cumulonimbus",
    "lacunosus":        "cirrocumulus",
    "lenticularis":     "altocumulus",
    "pileus":           "cumulus",
    "horseshoe vortex": "cumulus",
    "fluctus":          "cirrus",
    "asperitas":        "stratocumulus",
    "uncinus":          "cirrus",
    "floccus":          "cirrus",
    "castellanus":      "altocumulus",
    "distrail":         "altocumulus",
    "contrail":         "cirrus",
    "pyrocumulus":      "cumulus",
    "congestus":        "cumulus",
    "velum":            "cumulus",
    "pannus":           "cumulonimbus",
    "fractus":          "cumulus",
    "murus":            "cumulonimbus",
    # additional mappings
    "virga":            "altostratus",
    "fog":              "stratus",
    "fibrates":         "cirrus",
    "undulatus":        "altocumulus",
    "cap cloud":        "stratus",
}


def fix_cloud_type_from_subtype(df: pd.DataFrame) -> pd.DataFrame:
    """
    Where subtype1 is filled but cloud_type1 is empty, infer cloud_type1
    from SUBTYPE_TO_CLOUDTYPE and set cloud_type_fix = True.
    All other rows get cloud_type_fix = False.
    """
    df["cloud_type_fix"] = False

    blank = {"", "nan", "none"}

    def _is_blank(val) -> bool:
        return pd.isna(val) or str(val).strip().lower() in blank

    fixed = 0
    for idx in df.index:
        if not _is_blank(df.at[idx, "cloud_type1"]):
            continue
        subtype = df.at[idx, "subtype1"]
        if _is_blank(subtype):
            continue
        inferred = SUBTYPE_TO_CLOUDTYPE.get(str(subtype).strip().lower())
        if inferred:
            df.at[idx, "cloud_type1"]    = inferred
            df.at[idx, "cloud_type_fix"] = True
            fixed += 1

    print(f"Cloud type inferred from subtype: {fixed} row(s) updated.")
    return df


# -------------------------
# Main pipeline
# -------------------------

def run(input_path: Path, output_path: Path):
    if output_path.exists():
        raise FileExistsError(
            f"Output file already exists: {output_path}\n"
            "Use a new path to avoid overwriting."
        )

    print(f"Reading: {input_path}")
    df = pd.read_csv(input_path, dtype=str)   # read as str to avoid NaN float surprises
    # Re-parse numeric columns so downstream checks work
    for col in ("latitude", "longitude"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    print(f"Loaded {len(df)} rows, {len(df.columns)} columns.\n")

    # Step 1
    print("--- Step 1: Rename columns ---")
    df = fix_column_names(df)

    # Step 2
    print("\n--- Step 2: Reverse geocode missing locations ---")
    df = fix_missing_locations(df)

    # Step 3
    print("\n--- Step 3: Infer cloud_type1 from subtype1 ---")
    df = fix_cloud_type_from_subtype(df)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    print(f"\nDone. Wrote {len(df)} rows to: {output_path}")
