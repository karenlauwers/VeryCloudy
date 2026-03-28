"""
Task B — Fetch historical weather data from Open-Meteo for each cloud image.

Uses the Open-Meteo Historical Weather API (free, no key required):
    GET https://archive-api.open-meteo.com/v1/archive
        ?latitude=…&longitude=…&start_date=…&end_date=…&hourly=…&timezone=UTC

Follows the same async pattern as location.py (semaphore rate-limiting,
batch CSV flush, resume support).
"""

from verycloudy.config import (
    BATCH_FLUSH,
    OPEN_METEO_URL, OPEN_METEO_CONCURRENCY, OPEN_METEO_DELAY,
)

import asyncio
import calendar
import csv
import math
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import aiohttp
from aiohttp import ClientTimeout
import pandas as pd
from timezonefinder import TimezoneFinder
from tqdm import tqdm


# -------------------------
# Date/time → Unix helpers
# -------------------------

def _s(v) -> str:
    """Safely coerce a CSV value (possibly pandas NaN) to a stripped string."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    return str(v).strip()


def convert_to_unix(date_str, time_str,
                    date_utc=None, time_utc=None) -> int | None:
    """
    Convert date + time strings to a Unix UTC timestamp.
    Prefer UTC columns when available; otherwise treat local as UTC (best approx).
    Returns None if parsing fails.
    """
    # Prefer UTC columns if present
    d = _s(date_utc)
    t = _s(time_utc)
    if d and t:
        try:
            dt = datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M:%S")
            return int(calendar.timegm(dt.timetuple()))
        except ValueError:
            pass

    # Fall back to local date/time (treat as UTC)
    d = _s(date_str)
    t = _s(time_str)
    if not d:
        return None
    if not t:
        t = "12:00:00"  # midday fallback
    try:
        dt = datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M:%S")
        return int(calendar.timegm(dt.timetuple()))
    except ValueError:
        return None


_tf = TimezoneFinder()


def _local_to_unix(date_str, time_str, lat: float, lon: float) -> int | None:
    """
    Convert a naive local capture time to Unix UTC using the location's timezone.
    Falls back to treating the time as UTC if no timezone is found (e.g. open ocean).
    """
    d = _s(date_str)
    t = _s(time_str)
    if not d:
        return None
    if not t:
        t = "12:00:00"
    try:
        dt_naive = datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    tz_name = _tf.timezone_at(lat=lat, lng=lon)
    if tz_name:
        dt_local = dt_naive.replace(tzinfo=ZoneInfo(tz_name))
        return int(dt_local.astimezone(timezone.utc).timestamp())
    # No timezone found — treat as UTC
    return int(calendar.timegm(dt_naive.timetuple()))


# -------------------------
# Open-Meteo API call
# -------------------------

WEATHER_FIELDS = [
    "lightbox_id", "dt_unix", "date_taken_utc", "time_taken_utc",
    "temp", "feels_like", "pressure", "humidity", "dew_point",
    "clouds", "clouds_low", "clouds_mid", "clouds_high",
    "wind_speed", "wind_deg", "wind_gust", "visibility",
    "weather_code", "rain_1h", "snow_1h", "uvi",
]

# Note: temperature_850hPa, temperature_500hPa and cape are NOT available in the
# Open-Meteo historical archive endpoint (units returned as "undefined"). Omitted.
OPEN_METEO_VARS = (
    "temperature_2m,apparent_temperature,relative_humidity_2m,dew_point_2m,"
    "pressure_msl,cloud_cover,cloud_cover_low,cloud_cover_mid,cloud_cover_high,"
    "wind_speed_10m,wind_direction_10m,wind_gusts_10m,"
    "visibility,rain,snowfall,weather_code,uv_index"
)


def _iso_to_unix(s: str) -> int:
    """Convert Open-Meteo time string 'YYYY-MM-DDTHH:MM' to Unix timestamp (UTC)."""
    return int(calendar.timegm(datetime.strptime(s, "%Y-%m-%dT%H:%M").timetuple()))


async def fetch_weather(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    lat: float,
    lon: float,
    unix_ts: int,
) -> dict | None:
    """
    Call Open-Meteo archive for a single lat/lon/timestamp.
    Returns extracted weather dict or None on failure.
    """
    date_str = datetime.fromtimestamp(unix_ts, tz=timezone.utc).strftime("%Y-%m-%d")
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": date_str,
        "end_date": date_str,
        "hourly": OPEN_METEO_VARS,
        "timezone": "UTC",
    }
    async with sem:
        try:
            for attempt in range(3):
                async with session.get(OPEN_METEO_URL, params=params) as resp:
                    if resp.status == 429:
                        print("  [RATE LIMIT] waiting 60s …")
                        await asyncio.sleep(60)
                        continue
                    if resp.status != 200:
                        text = await resp.text()
                        print(f"  [ERROR] {resp.status}: {text[:120]}")
                        return None
                    body = await resp.json()
                    break
            else:
                return None  # all retries exhausted
        except Exception as exc:
            print(f"  [ERROR] weather fetch failed: {exc}")
            return None
        finally:
            await asyncio.sleep(OPEN_METEO_DELAY)

    hourly = body.get("hourly", {})
    times = hourly.get("time", [])
    if not times:
        return None

    # Pick the index of the hour closest to unix_ts
    target_hour = datetime.fromtimestamp(unix_ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:00")
    try:
        idx = times.index(target_hour)
    except ValueError:
        idx = min(range(len(times)), key=lambda i: abs(_iso_to_unix(times[i]) - unix_ts))

    def _h(key):
        vals = hourly.get(key, [])
        return vals[idx] if idx < len(vals) else None

    return {
        "temp":         _h("temperature_2m"),
        "feels_like":   _h("apparent_temperature"),
        "humidity":     _h("relative_humidity_2m"),
        "dew_point":    _h("dew_point_2m"),
        "pressure":     _h("pressure_msl"),
        "clouds":       _h("cloud_cover"),
        "clouds_low":   _h("cloud_cover_low"),
        "clouds_mid":   _h("cloud_cover_mid"),
        "clouds_high":  _h("cloud_cover_high"),
        "wind_speed":   _h("wind_speed_10m"),
        "wind_deg":     _h("wind_direction_10m"),
        "wind_gust":    _h("wind_gusts_10m"),
        "visibility":   _h("visibility"),
        "weather_code": _h("weather_code"),
        "rain_1h":      _h("rain"),
        "snow_1h":      _h("snowfall"),
        "uvi":          _h("uv_index"),
    }


# -------------------------
# Process one row
# -------------------------

async def process_row(row: dict, session: aiohttp.ClientSession,
                      sem: asyncio.Semaphore) -> dict:
    """Process a single CSV row: convert dt, call API, return result dict."""
    lightbox_id = row.get("lightbox_id")
    empty = {f: None for f in WEATHER_FIELDS}
    empty["lightbox_id"] = lightbox_id

    # Check for valid coordinates
    lat = row.get("latitude")
    lon = row.get("longitude")
    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return empty  # no location → empty weather
    if math.isnan(lat) or math.isnan(lon):
        return empty  # NaN from empty CSV cell → no location

    # Convert date/time to unix
    # Strategy depends on how reliable the time is:
    #   1) XMP gave real UTC columns → use directly
    #   2) Real capture time (EXIF/filename), naive local → convert via location timezone
    #   3) Fallback (upload date + manual 11am) → no real capture time, treat as UTC
    fallback_used = _s(row.get("fallback_used")).lower() == "true"
    d_utc = _s(row.get("date_taken_utc"))
    t_utc = _s(row.get("time_taken_utc"))

    if d_utc and t_utc:
        unix_ts = convert_to_unix("", "", d_utc, t_utc)
    elif not fallback_used:
        unix_ts = _local_to_unix(row.get("date_taken"), row.get("time_taken"), lat, lon)
    else:
        unix_ts = convert_to_unix(row.get("date_taken"), row.get("time_taken"))

    if unix_ts is None:
        return empty

    # Derive human-readable UTC date/time from the unix timestamp
    dt_utc = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
    date_taken_utc = dt_utc.strftime("%Y-%m-%d")
    time_taken_utc = dt_utc.strftime("%H:%M:%S")

    weather = await fetch_weather(session, sem, lat, lon, unix_ts)
    if weather is None:
        return empty

    return {
        "lightbox_id": lightbox_id,
        "dt_unix": unix_ts,
        "date_taken_utc": date_taken_utc,
        "time_taken_utc": time_taken_utc,
        **weather,
    }


# -------------------------
# Main pipeline
# -------------------------

async def run(input_path: Path, out_csv: Path):
    df = pd.read_csv(input_path)

    # Resume: skip already processed lightbox_ids
    processed_ids: set[str] = set()
    if out_csv.exists():
        try:
            prev = pd.read_csv(out_csv)
            if "lightbox_id" in prev.columns:
                processed_ids = set(prev["lightbox_id"].astype(str).tolist())
        except Exception:
            pass

    rows = []
    skipped_no_location = 0
    for _, r in df.iterrows():
        lid = str(r.get("lightbox_id", "")).strip()
        if lid and lid in processed_ids:
            continue
        lat, lon = r.get("latitude"), r.get("longitude")
        try:
            if math.isnan(float(lat)) or math.isnan(float(lon)):
                skipped_no_location += 1
                continue
        except (TypeError, ValueError):
            skipped_no_location += 1
            continue
        rows.append(r.to_dict())

    print(f"Rows to process: {len(rows)}  "
          f"(skipped {len(processed_ids)} already done, "
          f"{skipped_no_location} no location)")

    if not rows:
        print("Nothing to do.")
        return

    new_file = not out_csv.exists()
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    with out_csv.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=WEATHER_FIELDS)
        if new_file:
            writer.writeheader()

        timeout = ClientTimeout(total=60, connect=10, sock_read=40)
        connector = aiohttp.TCPConnector(limit=OPEN_METEO_CONCURRENCY, ttl_dns_cache=300)

        async with aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
            raise_for_status=False,
        ) as session:
            sem = asyncio.Semaphore(1)  # sequential: one request at a time
            buffer: list[dict] = []
            pbar = tqdm(total=len(rows), desc="Fetching weather", unit="row")

            for row in rows:
                res = await process_row(row, session, sem)
                buffer.append(res)
                if len(buffer) >= BATCH_FLUSH:
                    writer.writerows(buffer)
                    f.flush()
                    buffer.clear()
                pbar.update(1)

            pbar.close()

            if buffer:
                writer.writerows(buffer)
                f.flush()

    print(f"Done. Wrote: {out_csv}")
