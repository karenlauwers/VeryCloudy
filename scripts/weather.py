"""
Task B — Fetch historical weather data from OpenWeatherMap for each cloud image.

Uses the One Call 3.0 Timemachine endpoint:
    GET /data/3.0/onecall/timemachine?lat=…&lon=…&dt=…&appid=…&units=metric

Follows the same async pattern as location.py (semaphore rate-limiting,
batch CSV flush, resume support).
"""

from verycloudy.config import (
    BATCH_FLUSH,
    OWM_WEATHER_URL, OWM_WEATHER_CONCURRENCY, OWM_WEATHER_DELAY,
)

import asyncio
import calendar
import csv
from datetime import datetime, timezone
from pathlib import Path

import aiohttp
from aiohttp import ClientTimeout
import pandas as pd
from tqdm import tqdm


# -------------------------
# Date/time → Unix helpers
# -------------------------

def convert_to_unix(date_str: str, time_str: str,
                    date_utc: str | None = None, time_utc: str | None = None) -> int | None:
    """
    Convert date + time strings to a Unix UTC timestamp.
    Prefer UTC columns when available; otherwise treat local as UTC (best approx).
    Returns None if parsing fails.
    """
    # Prefer UTC columns if present
    d = (date_utc or "").strip()
    t = (time_utc or "").strip()
    if d and t:
        try:
            dt = datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M:%S")
            return int(calendar.timegm(dt.timetuple()))
        except ValueError:
            pass

    # Fall back to local date/time (treat as UTC)
    d = (date_str or "").strip()
    t = (time_str or "").strip()
    if not d:
        return None
    if not t:
        t = "12:00:00"  # midday fallback
    try:
        dt = datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M:%S")
        return int(calendar.timegm(dt.timetuple()))
    except ValueError:
        return None


# -------------------------
# OWM API call
# -------------------------

WEATHER_FIELDS = [
    "lightbox_id", "dt_unix",
    "temp", "feels_like", "pressure", "humidity", "dew_point", "clouds",
    "wind_speed", "wind_deg", "wind_gust", "visibility",
    "weather_id", "weather_main", "weather_description",
    "rain_1h", "snow_1h", "uvi",
]


def _extract_weather(data_entry: dict) -> dict:
    """Pull relevant fields from a single OWM timemachine data entry."""
    weather_block = data_entry.get("weather", [{}])[0] if data_entry.get("weather") else {}
    return {
        "dt_unix": data_entry.get("dt"),
        "temp": data_entry.get("temp"),
        "feels_like": data_entry.get("feels_like"),
        "pressure": data_entry.get("pressure"),
        "humidity": data_entry.get("humidity"),
        "dew_point": data_entry.get("dew_point"),
        "clouds": data_entry.get("clouds"),
        "wind_speed": data_entry.get("wind_speed"),
        "wind_deg": data_entry.get("wind_deg"),
        "wind_gust": data_entry.get("wind_gust"),
        "visibility": data_entry.get("visibility"),
        "weather_id": weather_block.get("id"),
        "weather_main": weather_block.get("main"),
        "weather_description": weather_block.get("description"),
        "rain_1h": (data_entry.get("rain") or {}).get("1h"),
        "snow_1h": (data_entry.get("snow") or {}).get("1h"),
        "uvi": data_entry.get("uvi"),
    }


def _pick_closest(data_entries: list[dict], target_ts: int) -> dict:
    """From the hourly data array, pick the entry closest to target_ts."""
    if not data_entries:
        return {}
    return min(data_entries, key=lambda e: abs(e.get("dt", 0) - target_ts))


async def fetch_weather(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    lat: float,
    lon: float,
    unix_ts: int,
    api_key: str,
) -> dict | None:
    """
    Call OWM timemachine for a single lat/lon/timestamp.
    Returns extracted weather dict or None on failure.
    """
    params = {
        "lat": lat,
        "lon": lon,
        "dt": unix_ts,
        "appid": api_key,
        "units": "metric",
    }
    async with sem:
        try:
            async with session.get(OWM_WEATHER_URL, params=params) as resp:
                if resp.status == 401 or resp.status == 403:
                    text = await resp.text()
                    print(f"  [AUTH ERROR] {resp.status}: {text[:120]}")
                    return None
                if resp.status == 429:
                    # Rate limited — back off and retry once
                    await asyncio.sleep(5)
                    async with session.get(OWM_WEATHER_URL, params=params) as retry:
                        if retry.status != 200:
                            return None
                        body = await retry.json()
                else:
                    if resp.status != 200:
                        return None
                    body = await resp.json()

            data_entries = body.get("data", [])
            best = _pick_closest(data_entries, unix_ts)
            if not best:
                return None
            return _extract_weather(best)

        except Exception as exc:
            print(f"  [ERROR] weather fetch failed: {exc}")
            return None
        finally:
            await asyncio.sleep(OWM_WEATHER_DELAY)


# -------------------------
# Process one row
# -------------------------

async def process_row(row: dict, session: aiohttp.ClientSession,
                      sem: asyncio.Semaphore, api_key: str) -> dict:
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

    # Convert date/time to unix
    unix_ts = convert_to_unix(
        row.get("date_taken", ""),
        row.get("time_taken", ""),
        row.get("date_taken_utc"),
        row.get("time_taken_utc"),
    )
    if unix_ts is None:
        return empty

    weather = await fetch_weather(session, sem, lat, lon, unix_ts, api_key)
    if weather is None:
        return empty

    return {"lightbox_id": lightbox_id, **weather}


# -------------------------
# Main pipeline
# -------------------------

async def run(input_path: Path, out_csv: Path, api_key: str):
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
    for _, r in df.iterrows():
        lid = str(r.get("lightbox_id", "")).strip()
        if lid and lid in processed_ids:
            continue
        rows.append(r.to_dict())

    print(f"Rows to process: {len(rows)}  (skipped {len(processed_ids)} already done)")

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
        connector = aiohttp.TCPConnector(limit=OWM_WEATHER_CONCURRENCY, ttl_dns_cache=300)

        async with aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
            raise_for_status=False,
        ) as session:
            sem = asyncio.Semaphore(OWM_WEATHER_CONCURRENCY)
            buffer: list[dict] = []
            pbar = tqdm(total=len(rows), desc="Fetching weather", unit="row")

            async def worker(row):
                res = await process_row(row, session, sem, api_key)
                buffer.append(res)
                if len(buffer) >= BATCH_FLUSH:
                    writer.writerows(buffer)
                    f.flush()
                    buffer.clear()
                pbar.update(1)

            tasks = [asyncio.create_task(worker(r)) for r in rows]
            await asyncio.gather(*tasks)
            pbar.close()

            if buffer:
                writer.writerows(buffer)
                f.flush()

    print(f"Done. Wrote: {out_csv}")
