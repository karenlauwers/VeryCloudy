"""
Generate negative-class rows (clear sky) for the ML model.

Reuses confirmed locations from cloud_gallery_full.csv. For each location a random
month is queried from Open-Meteo; hourly slots that are truly clear (weather_code==0,
cloud_cover<=10, daytime 07-18 UTC) are collected as output rows until TARGET_ROWS
is reached.

Columns match cloud_gallery_full.csv. Image/title/tag columns are empty.
cloud_type1-3 and subtype1-2 are empty — that IS the negative label.

Run via: python scripts/main_no_clouds.py
"""

import asyncio
import calendar
import csv
import math
import random
from datetime import datetime, timezone
from pathlib import Path

import aiohttp
from aiohttp import ClientTimeout
import pandas as pd
from tqdm import tqdm

from verycloudy.config import (
    OPEN_METEO_URL, OPEN_METEO_CONCURRENCY, OPEN_METEO_DELAY, BATCH_FLUSH,
)

# -------------------------
# Configuration
# -------------------------

TARGET_ROWS = 100   # adjust after seeing per-class distribution in Part 3
MAX_PER_LOCATION = 10  # max clear-sky rows taken per location (ensures geographic spread)

# Date range to draw random months from (matches the CAS gallery dataset)
YEAR_MIN = 2005
YEAR_MAX = 2026

# Only collect hours during daylight (UTC) — matches when photos are taken
HOUR_MIN = 7
HOUR_MAX = 18

# Clear-sky thresholds
MAX_CLOUD_COVER = 10   # %
CLEAR_WEATHER_CODE = 0

# Open-Meteo variables (same set as weather.py — no pressure-level vars, not in archive)
OPEN_METEO_VARS = (
    "temperature_2m,apparent_temperature,relative_humidity_2m,dew_point_2m,"
    "pressure_msl,cloud_cover,cloud_cover_low,cloud_cover_mid,cloud_cover_high,"
    "wind_speed_10m,wind_direction_10m,wind_gusts_10m,"
    "visibility,rain,snowfall,weather_code,uv_index"
)

# Output columns — must match cloud_gallery_full.csv schema exactly
OUTPUT_FIELDS = [
    # identity / image (empty for synthetic rows)
    "lightbox_id", "image_url", "date_iso", "date_raw",
    "author_name", "author_profile", "title", "tags",
    "status", "source_field", "fallback_used", "error",
    # date/time
    "date_taken", "time_taken", "date_taken_utc", "time_taken_utc", "dt_unix",
    # location
    "city", "region", "country", "latitude", "longitude", "location_source",
    # weather
    "temp", "feels_like", "pressure", "humidity", "dew_point",
    "clouds", "clouds_low", "clouds_mid", "clouds_high",
    "wind_speed", "wind_deg", "wind_gust", "visibility",
    "weather_code", "rain_1h", "snow_1h", "uvi",
    # cloud classification (empty = negative label)
    "cloud_type1", "cloud_type2", "cloud_type3",
    "subtype1", "subtype2",
]


# -------------------------
# Open-Meteo helpers
# -------------------------

def _random_month(rng: random.Random) -> tuple[int, int]:
    """Return a random (year, month) within the configured date range."""
    year = rng.randint(YEAR_MIN, YEAR_MAX)
    month = rng.randint(1, 12)
    return year, month


def _month_date_range(year: int, month: int) -> tuple[str, str]:
    """Return (start_date, end_date) strings for a full calendar month."""
    last_day = calendar.monthrange(year, month)[1]
    return f"{year}-{month:02d}-01", f"{year}-{month:02d}-{last_day:02d}"


async def fetch_month(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    lat: float,
    lon: float,
    year: int,
    month: int,
) -> list[dict]:
    """
    Query Open-Meteo for a full month at lat/lon.
    Returns a list of dicts, one per qualifying clear-sky daytime hour.
    """
    start, end = _month_date_range(year, month)
    params = {
        "latitude":   lat,
        "longitude":  lon,
        "start_date": start,
        "end_date":   end,
        "hourly":     OPEN_METEO_VARS,
        "timezone":   "UTC",
    }

    async with sem:
        try:
            for _ in range(3):
                async with session.get(OPEN_METEO_URL, params=params) as resp:
                    if resp.status == 429:
                        print("  [RATE LIMIT] waiting 60s ...")
                        await asyncio.sleep(60)
                        continue
                    if resp.status != 200:
                        return []
                    body = await resp.json()
                    break
            else:
                return []
        except Exception as exc:
            print(f"  [ERROR] {exc}")
            return []
        finally:
            await asyncio.sleep(OPEN_METEO_DELAY)

    hourly = body.get("hourly", {})
    times = hourly.get("time", [])
    if not times:
        return []

    def _v(key, idx):
        vals = hourly.get(key, [])
        return vals[idx] if idx < len(vals) else None

    results = []
    for idx, t in enumerate(times):
        # Parse hour from "YYYY-MM-DDTHH:MM"
        try:
            hour = int(t[11:13])
        except (ValueError, IndexError):
            continue

        if not (HOUR_MIN <= hour <= HOUR_MAX):
            continue

        code = _v("weather_code", idx)
        cover = _v("cloud_cover", idx)

        if code is None or cover is None:
            continue
        if int(code) != CLEAR_WEATHER_CODE:
            continue
        if float(cover) > MAX_CLOUD_COVER:
            continue

        # Parse datetime
        dt_naive = datetime.strptime(t, "%Y-%m-%dT%H:%M")
        dt_utc = dt_naive.replace(tzinfo=timezone.utc)
        unix_ts = int(dt_utc.timestamp())

        results.append({
            "time_str":    t,
            "date_taken":  dt_utc.strftime("%Y-%m-%d"),
            "time_taken":  dt_utc.strftime("%H:%M:%S"),
            "dt_unix":     unix_ts,
            "temp":        _v("temperature_2m", idx),
            "feels_like":  _v("apparent_temperature", idx),
            "humidity":    _v("relative_humidity_2m", idx),
            "dew_point":   _v("dew_point_2m", idx),
            "pressure":    _v("pressure_msl", idx),
            "clouds":      cover,
            "clouds_low":  _v("cloud_cover_low", idx),
            "clouds_mid":  _v("cloud_cover_mid", idx),
            "clouds_high": _v("cloud_cover_high", idx),
            "wind_speed":  _v("wind_speed_10m", idx),
            "wind_deg":    _v("wind_direction_10m", idx),
            "wind_gust":   _v("wind_gusts_10m", idx),
            "visibility":  _v("visibility", idx),
            "weather_code": code,
            "rain_1h":     _v("rain", idx),
            "snow_1h":     _v("snowfall", idx),
            "uvi":         _v("uv_index", idx),
        })

    return results


def build_row(loc: dict, weather: dict, counter: int) -> dict:
    """Assemble one output row from a location dict and a weather hour dict."""
    row = {f: None for f in OUTPUT_FIELDS}
    row["lightbox_id"] = f"CLEAR_{counter:06d}"
    # location
    row["latitude"]        = loc.get("latitude")
    row["longitude"]       = loc.get("longitude")
    row["city"]            = loc.get("city")
    row["region"]          = loc.get("region")
    row["country"]         = loc.get("country")
    row["location_source"] = loc.get("location_source")
    # date/time (UTC = local because we requested UTC from Open-Meteo)
    row["date_taken"]      = weather["date_taken"]
    row["time_taken"]      = weather["time_taken"]
    row["date_taken_utc"]  = weather["date_taken"]
    row["time_taken_utc"]  = weather["time_taken"]
    row["dt_unix"]         = weather["dt_unix"]
    # weather
    for field in ("temp", "feels_like", "humidity", "dew_point", "pressure",
                  "clouds", "clouds_low", "clouds_mid", "clouds_high",
                  "wind_speed", "wind_deg", "wind_gust", "visibility",
                  "weather_code", "rain_1h", "snow_1h", "uvi"):
        row[field] = weather.get(field)
    # cloud_type1-3, subtype1-2 stay None → negative label
    return row


# -------------------------
# Main pipeline
# -------------------------

async def run(locations_csv: Path, out_csv: Path, target: int = TARGET_ROWS):
    if out_csv.exists():
        raise FileExistsError(
            f"Output file already exists: {out_csv}\n"
            "Use a new path to avoid overwriting."
        )

    # Load unique locations (drop duplicates on lat/lon)
    df = pd.read_csv(locations_csv)
    loc_cols = ["latitude", "longitude", "city", "region", "country", "location_source"]
    locs = (
        df[loc_cols]
        .dropna(subset=["latitude", "longitude"])
        .drop_duplicates(subset=["latitude", "longitude"])
        .to_dict("records")
    )

    rng = random.Random(42)   # fixed seed → reproducible
    rng.shuffle(locs)

    print(f"Unique locations available: {len(locs)}")
    print(f"Target clear-sky rows:      {target}")

    out_csv.parent.mkdir(parents=True, exist_ok=True)

    collected = 0
    counter = 1

    timeout = ClientTimeout(total=90, connect=10, sock_read=60)
    connector = aiohttp.TCPConnector(limit=OPEN_METEO_CONCURRENCY, ttl_dns_cache=300)

    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        buffer = []

        async with aiohttp.ClientSession(
            timeout=timeout, connector=connector, raise_for_status=False
        ) as session:
            sem = asyncio.Semaphore(OPEN_METEO_CONCURRENCY)
            pbar = tqdm(total=target, desc="Collecting clear-sky rows", unit="row")

            for loc in locs:
                if collected >= target:
                    break

                lat = float(loc["latitude"])
                lon = float(loc["longitude"])
                if math.isnan(lat) or math.isnan(lon):
                    continue

                year, month = _random_month(rng)
                clear_hours = await fetch_month(session, sem, lat, lon, year, month)

                # If too few clear hours found, try one more random month
                if not clear_hours:
                    year, month = _random_month(rng)
                    clear_hours = await fetch_month(session, sem, lat, lon, year, month)

                rng.shuffle(clear_hours)
                loc_count = 0
                for weather in clear_hours:
                    if collected >= target:
                        break
                    if loc_count >= MAX_PER_LOCATION:
                        break
                    row = build_row(loc, weather, counter)
                    buffer.append(row)
                    counter += 1
                    collected += 1
                    loc_count += 1
                    pbar.update(1)

                    if len(buffer) >= BATCH_FLUSH:
                        writer.writerows(buffer)
                        f.flush()
                        buffer.clear()

            pbar.close()
            if buffer:
                writer.writerows(buffer)
                f.flush()

    print(f"\nDone. Wrote {collected} clear-sky rows to: {out_csv}")
    if collected < target:
        print(
            f"  WARNING: only {collected}/{target} rows collected.\n"
            f"  Try running again with more locations in the input file."
        )
