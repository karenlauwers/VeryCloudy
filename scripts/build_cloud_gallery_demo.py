"""
Demo pipeline — builds cloud_gallery_full_demo.csv end-to-end.

Runs all 11 steps of the full pipeline on a small dataset (~80 photos):
  1.  Scrape CAS gallery           → cloud_gallery_demo.csv
  2.  Extract date/time from EXIF  → clouds_date_demo.csv
  3.  Merge scrape + date          → cloud_gallery_with_date_demo.csv
  4.  Extract location             → clouds_location_demo.csv
  5.  Merge with_date + location   → cloud_gallery_with_date_loc_demo.csv
  6.  Fetch weather (Open-Meteo)   → clouds_weather_demo.csv
  7.  Merge with_date_loc + weather→ cloud_gallery_with_date_loc_weather_demo.csv
  8.  Extract cloud types          → cloud_gallery_all_info_demo.csv
  9.  Post-processing / clean-up   → cloud_gallery_all_info_clean_demo.csv
  10. Generate no-cloud rows       → no_clouds_demo.csv
  11. Concat cloud + no-cloud      → cloud_gallery_full_demo.csv

Usage (from project root):
    python scripts/build_cloud_gallery_demo.py

Requirements:
  - Set COOKIE below (copy from your browser session on cloudappreciationsociety.org)
  - Set OWM_API_KEY in a .env file at the project root, or as an OS environment variable
"""

import asyncio
import os
import sys
from pathlib import Path

import pandas as pd

# ── Make scripts/ and src/ importable ─────────────────────────────────────────
_SCRIPTS_DIR = Path(__file__).resolve().parent
_SRC_DIR = _SCRIPTS_DIR.parent / "src"
sys.path.insert(0, str(_SCRIPTS_DIR))
sys.path.insert(0, str(_SRC_DIR))

from verycloudy.config import (
    FILEPATH_CLOUDS_CSV_DEMO,
    FILEPATH_DATE_DEMO,
    FILEPATH_CLOUDS_WITH_DATE_DEMO,
    FILEPATH_LOCATION_DEMO,
    FILEPATH_CLOUDS_WITH_DATE_LOC_DEMO,
    FILEPATH_WEATHER_DEMO,
    FILEPATH_CLOUDS_WITH_DATE_LOC_WEATHER_DEMO,
    FILEPATH_CLOUDS_WITH_DATE_LOC_WEATHER_TYPE_DEMO,
    FILEPATH_CLOUDS_ALL_INFO_CLEAN_DEMO,
    FILEPATH_NO_CLOUDS_DEMO,
    FILEPATH_FULL_DEMO,
)

# ── Configuration ──────────────────────────────────────────────────────────────

# Paste your browser session cookie here (needed to access the CAS gallery):
COOKIE = ""  # e.g. "aelia_customer_country=BE; aelia_cs_selected_currency=EUR; ..."

# Number of gallery pages to scrape (≈16 photos per page → 5 pages ≈ 80 photos)
DEMO_PAGES = 5

# Number of synthetic no-cloud rows to generate
DEMO_NO_CLOUD_ROWS = 5


# ── Helpers ────────────────────────────────────────────────────────────────────

def _step(n: int, title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  STEP {n}: {title}")
    print(f"{'=' * 60}")


def _load_owm_api_key() -> str:
    try:
        from dotenv import load_dotenv, find_dotenv
        dotenv_file = find_dotenv(usecwd=False)
        if dotenv_file:
            load_dotenv(dotenv_file)
    except Exception:
        pass
    return os.environ.get("OWM_API_KEY", "")


def _merge_left(left_path: Path, right_path: Path, out_path: Path,
                drop_from_right: list[str] | None = None) -> None:
    """Left-join two CSVs on lightbox_id and write result.
    drop_from_right: columns to drop from the right CSV before merging
    (use for columns that exist in both files to avoid _x/_y suffixes).
    """
    df_left  = pd.read_csv(left_path,  low_memory=False)
    df_right = pd.read_csv(right_path, low_memory=False)
    if drop_from_right:
        df_right = df_right.drop(columns=[c for c in drop_from_right if c in df_right.columns])
    merged = pd.merge(df_left, df_right, on="lightbox_id", how="left")
    merged.to_csv(out_path, index=False)
    print(f"  Merged {len(df_left)} + {len(df_right)} rows → {len(merged)} rows")
    print(f"  Written to: {out_path.name}")


def _preflight_check() -> None:
    """Abort if any demo output file already exists — never overwrite."""
    demo_files = [
        FILEPATH_CLOUDS_CSV_DEMO,
        FILEPATH_DATE_DEMO,
        FILEPATH_CLOUDS_WITH_DATE_DEMO,
        FILEPATH_LOCATION_DEMO,
        FILEPATH_CLOUDS_WITH_DATE_LOC_DEMO,
        FILEPATH_WEATHER_DEMO,
        FILEPATH_CLOUDS_WITH_DATE_LOC_WEATHER_DEMO,
        FILEPATH_CLOUDS_WITH_DATE_LOC_WEATHER_TYPE_DEMO,
        FILEPATH_CLOUDS_ALL_INFO_CLEAN_DEMO,
        FILEPATH_NO_CLOUDS_DEMO,
        FILEPATH_FULL_DEMO,
    ]
    existing = [f for f in demo_files if f.exists()]
    if existing:
        names = "\n  ".join(f.name for f in existing)
        raise FileExistsError(
            f"The following demo files already exist — delete them first to re-run:\n  {names}"
        )


# ── Pipeline ───────────────────────────────────────────────────────────────────

async def main() -> None:

    _preflight_check()

    # ── STEP 1: Scrape CAS gallery ────────────────────────────────────────────
    _step(1, "Scraping CAS gallery")
    from scraping_by_api import crawl_all_clouds, save_csv

    rows = crawl_all_clouds(
        cats="",
        photographer="",
        sleep_sec=0.8,
        max_pages=DEMO_PAGES,
        cookie_string=COOKIE if COOKIE else None,
        seen_ids=set(),
        stop_when_all_seen_pages=0,  # disable early-stop for demo
    )
    save_csv(rows, FILEPATH_CLOUDS_CSV_DEMO)
    print(f"  Scraped {len(rows)} photos → {FILEPATH_CLOUDS_CSV_DEMO.name}")

    # ── STEP 2: Extract date/time from EXIF ──────────────────────────────────
    _step(2, "Extracting date/time from EXIF metadata")
    from date import run as date_run
    await date_run(FILEPATH_CLOUDS_CSV_DEMO, FILEPATH_DATE_DEMO)

    # ── STEP 3: Merge scrape + date ───────────────────────────────────────────
    _step(3, "Merging scrape data with date/time")
    # image_url exists in both files — drop from date output to avoid _x/_y suffixes
    _merge_left(FILEPATH_CLOUDS_CSV_DEMO, FILEPATH_DATE_DEMO, FILEPATH_CLOUDS_WITH_DATE_DEMO,
                drop_from_right=["image_url"])

    # ── STEP 4: Extract location ──────────────────────────────────────────────
    _step(4, "Extracting location from image metadata / NER + geocoding")
    api_key = _load_owm_api_key()
    if not api_key:
        raise RuntimeError(
            "OWM_API_KEY is missing.\n"
            "Add it to a .env file at the project root:  OWM_API_KEY=YOUR_KEY"
        )
    from location import run as location_run
    await location_run(FILEPATH_CLOUDS_WITH_DATE_DEMO, FILEPATH_LOCATION_DEMO, api_key)

    # ── STEP 5: Merge with_date + location ────────────────────────────────────
    _step(5, "Merging with location data")
    _merge_left(FILEPATH_CLOUDS_WITH_DATE_DEMO, FILEPATH_LOCATION_DEMO, FILEPATH_CLOUDS_WITH_DATE_LOC_DEMO)

    # ── STEP 6: Fetch historical weather (Open-Meteo) ─────────────────────────
    _step(6, "Fetching historical weather data from Open-Meteo")
    from weather import run as weather_run
    await weather_run(FILEPATH_CLOUDS_WITH_DATE_LOC_DEMO, FILEPATH_WEATHER_DEMO)

    # ── STEP 7: Merge with_date_loc + weather ─────────────────────────────────
    _step(7, "Merging with weather data")
    _merge_left(FILEPATH_CLOUDS_WITH_DATE_LOC_DEMO, FILEPATH_WEATHER_DEMO, FILEPATH_CLOUDS_WITH_DATE_LOC_WEATHER_DEMO)

    # ── STEP 8: Extract cloud types and subtypes ──────────────────────────────
    _step(8, "Extracting cloud types and subtypes from tags")
    from cloudtype import run as cloudtype_run
    cloudtype_run(FILEPATH_CLOUDS_WITH_DATE_LOC_WEATHER_DEMO, FILEPATH_CLOUDS_WITH_DATE_LOC_WEATHER_TYPE_DEMO)

    # ── STEP 9: Post-processing / clean-up ────────────────────────────────────
    _step(9, "Post-processing: column renames, reverse geocoding, subtype fallback")
    from update import run as update_run
    update_run(FILEPATH_CLOUDS_WITH_DATE_LOC_WEATHER_TYPE_DEMO, FILEPATH_CLOUDS_ALL_INFO_CLEAN_DEMO)

    # ── STEP 10: Generate no-cloud (clear-sky) rows ───────────────────────────
    _step(10, f"Generating {DEMO_NO_CLOUD_ROWS} synthetic no-cloud rows from Open-Meteo")
    from no_clouds import run as no_clouds_run
    await no_clouds_run(
        FILEPATH_CLOUDS_ALL_INFO_CLEAN_DEMO,
        FILEPATH_NO_CLOUDS_DEMO,
        target=DEMO_NO_CLOUD_ROWS,
    )

    # ── STEP 11: Concat cloud + no-cloud ─────────────────────────────────────
    _step(11, "Concatenating cloud and no-cloud rows into final dataset")
    df_clouds   = pd.read_csv(FILEPATH_CLOUDS_ALL_INFO_CLEAN_DEMO, low_memory=False)
    df_no_cloud = pd.read_csv(FILEPATH_NO_CLOUDS_DEMO, low_memory=False)
    df_full = pd.concat([df_clouds, df_no_cloud], ignore_index=True)
    df_full.to_csv(FILEPATH_FULL_DEMO, index=False)
    print(f"  {len(df_clouds)} cloud rows + {len(df_no_cloud)} no-cloud rows = {len(df_full)} total")
    print(f"  Written to: {FILEPATH_FULL_DEMO.name}")

    print(f"\n{'=' * 60}")
    print(f"  DONE — demo dataset complete: {FILEPATH_FULL_DEMO.name}")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    asyncio.run(main())
