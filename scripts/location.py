from verycloudy.config import (
    RANGE_BYTES, GLOBAL_CONCURRENCY, PER_HOST_LIMIT, BATCH_FLUSH,
    DEFAULT_HEADERS,
    OWM_GEOCODING_URL, NOMINATIM_USER_AGENT, NOMINATIM_DELAY, OWM_GEOCODING_CONCURRENCY,
)

import asyncio
import csv
import re
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
from aiohttp import ClientTimeout
import exifread
import pandas as pd
from PIL import Image
from tqdm import tqdm

import spacy
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError

# -------------------------
# Helpers: GPS conversion
# -------------------------

def _rational_to_float(val) -> float | None:
    """Convert an exifread IfdTag or a PIL rational tuple/float to a float."""
    try:
        # exifread IfdTag with .values list of Ratio objects
        if hasattr(val, "values"):
            parts = val.values
            if len(parts) == 3:
                d = float(parts[0].num) / float(parts[0].den)
                m = float(parts[1].num) / float(parts[1].den)
                s = float(parts[2].num) / float(parts[2].den)
                return d + m / 60 + s / 3600
            if len(parts) == 1:
                return float(parts[0].num) / float(parts[0].den)
        # PIL: list/tuple of (num, den) tuples or plain float
        if isinstance(val, (list, tuple)):
            if len(val) == 3:
                def _frac(x):
                    if isinstance(x, tuple):
                        return x[0] / x[1]
                    return float(x)
                d, m, s = _frac(val[0]), _frac(val[1]), _frac(val[2])
                return d + m / 60 + s / 3600
        return float(val)
    except Exception:
        return None


def dms_to_decimal(dms_val, ref: str) -> float | None:
    """Convert DMS value + hemisphere ref to signed decimal degrees."""
    deg = _rational_to_float(dms_val)
    if deg is None:
        return None
    if ref in ("S", "W"):
        deg = -deg
    return round(deg, 6)


# -------------------------
# Helpers: EXIF/IPTC/XMP location extraction
# -------------------------

def extract_gps_exifread(img_bytes: bytes) -> dict | None:
    """Try exifread for GPS tags. Returns {latitude, longitude} or None."""
    try:
        bio = BytesIO(img_bytes)
        tags = exifread.process_file(bio, details=False, strict=False)
        lat_tag = tags.get("GPS GPSLatitude")
        lat_ref = str(tags.get("GPS GPSLatitudeRef", "N")).strip()
        lon_tag = tags.get("GPS GPSLongitude")
        lon_ref = str(tags.get("GPS GPSLongitudeRef", "E")).strip()
        if lat_tag and lon_tag:
            lat = dms_to_decimal(lat_tag, lat_ref)
            lon = dms_to_decimal(lon_tag, lon_ref)
            if lat is not None and lon is not None:
                return {"latitude": lat, "longitude": lon}
    except Exception:
        pass
    return None


def extract_gps_pillow(img_bytes: bytes) -> dict | None:
    """Try PIL GPSInfo IFD (tag 34853) for GPS coordinates. Returns {latitude, longitude} or None."""
    try:
        with Image.open(BytesIO(img_bytes)) as im:
            exif = im.getexif()
            if not exif:
                return None
            gps_ifd = exif.get_ifd(0x8825)
            if not gps_ifd:
                return None
            # Tag IDs: 1=GPSLatitudeRef, 2=GPSLatitude, 3=GPSLongitudeRef, 4=GPSLongitude
            lat_ref = gps_ifd.get(1, "N")
            lat_val = gps_ifd.get(2)
            lon_ref = gps_ifd.get(3, "E")
            lon_val = gps_ifd.get(4)
            if lat_val and lon_val:
                lat = dms_to_decimal(lat_val, str(lat_ref).strip())
                lon = dms_to_decimal(lon_val, str(lon_ref).strip())
                if lat is not None and lon is not None:
                    return {"latitude": lat, "longitude": lon}
    except Exception:
        pass
    return None


def extract_xmp_location(img_bytes: bytes) -> dict:
    """
    Parse embedded XMP packet for location fields.
    Returns a dict with keys city, region, country, latitude, longitude (all may be None).
    """
    result = {"city": None, "region": None, "country": None, "latitude": None, "longitude": None}
    try:
        start = img_bytes.find(b"<x:xmpmeta")
        if start == -1:
            return result
        end = img_bytes.find(b"</x:xmpmeta>", start)
        if end == -1:
            return result
        xmp = img_bytes[start:end + 12].decode("utf-8", errors="ignore")

        def _find(tag):
            m = re.search(rf"<\s*{tag}[^>]*>(.*?)</\s*{tag}\s*>", xmp,
                          flags=re.IGNORECASE | re.DOTALL)
            return m.group(1).strip() if m else None

        city = _find(r"photoshop:City")
        state = _find(r"photoshop:State")
        country = _find(r"photoshop:Country")
        iptc_loc = _find(r"Iptc4xmpCore:Location")

        result["city"] = city or iptc_loc
        result["region"] = state
        result["country"] = country

        # Optional: GPS in XMP (decimal string, e.g. "48.8566N" or "48.8566")
        xmp_lat = _find(r"exif:GPSLatitude")
        xmp_lon = _find(r"exif:GPSLongitude")
        if xmp_lat and xmp_lon:
            try:
                def _parse_xmp_coord(s):
                    s = s.strip()
                    sign = -1 if s[-1] in ("S", "W") else 1
                    s = s.rstrip("NSEWnsew").strip()
                    # Could be DMS "48,51.3396N" or decimal "48.8566"
                    if "," in s:
                        parts = s.split(",")
                        d = float(parts[0])
                        m = float(parts[1]) if len(parts) > 1 else 0.0
                        sec = float(parts[2]) if len(parts) > 2 else 0.0
                        return sign * (d + m / 60 + sec / 3600)
                    return sign * float(s)
                result["latitude"] = round(_parse_xmp_coord(xmp_lat), 6)
                result["longitude"] = round(_parse_xmp_coord(xmp_lon), 6)
            except Exception:
                pass
    except Exception:
        pass
    return result


def extract_location_from_metadata(img_bytes: bytes) -> dict | None:
    """
    Combine GPS and XMP/IPTC extraction.
    Returns a dict with city/region/country/latitude/longitude if at least lat/lon found, else None.
    """
    # 1) GPS coordinates
    gps = extract_gps_exifread(img_bytes) or extract_gps_pillow(img_bytes)

    # 2) XMP text fields + optional XMP GPS
    xmp = extract_xmp_location(img_bytes)

    lat = (gps or {}).get("latitude") or xmp.get("latitude")
    lon = (gps or {}).get("longitude") or xmp.get("longitude")

    if lat is None or lon is None:
        return None

    return {
        "city": xmp.get("city"),
        "region": xmp.get("region"),
        "country": xmp.get("country"),
        "latitude": lat,
        "longitude": lon,
    }


# -------------------------
# Helpers: Title-based extraction
# -------------------------

_PREP_PATTERN = re.compile(
    r"(?:in|over|near|above|from|at|around|of)\s+"
    r"("
    r"[A-Z][a-zA-Z\u00C0-\u024F\s\-]+"
    r"(?:,\s*[A-Z][a-zA-Z\u00C0-\u024F\s\-]+){0,2}"
    r")"
    r"(?=[,\.;]|\s+[a-z]|$)",
    flags=re.UNICODE,
)


def extract_location_from_title(title: str, nlp) -> str | None:
    """
    Step 1: preposition-anchored regex covering:
      - country only         e.g. "in France"
      - city, country        e.g. "over Paris, France"
      - city, region, country e.g. "near Paris, Île-de-France, France"
    Step 2: spaCy GPE/LOC NER as fallback.
    Returns a location string or None.
    """
    if not title or not isinstance(title, str):
        return None

    m = _PREP_PATTERN.search(title)
    if m:
        return m.group(1).strip().rstrip(",").strip()

    # spaCy fallback
    doc = nlp(title)
    entities = [ent.text for ent in doc.ents if ent.label_ in ("GPE", "LOC")]
    if entities:
        return ", ".join(entities)

    return None


# -------------------------
# Geocoding
# -------------------------

async def geocode_owm(location_str: str, session: aiohttp.ClientSession,
                      sem: asyncio.Semaphore, api_key: str) -> dict | None:
    """Query OWM Geocoding API. Returns location dict or None."""
    if not api_key:
        return None
    params = {"q": location_str, "limit": 1, "appid": api_key}
    async with sem:
        try:
            async with session.get(OWM_GEOCODING_URL, params=params) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                if not data:
                    return None
                hit = data[0]
                return {
                    "city": hit.get("name"),
                    "region": hit.get("state"),
                    "country": hit.get("country"),
                    "latitude": round(float(hit["lat"]), 6),
                    "longitude": round(float(hit["lon"]), 6),
                }
        except Exception:
            return None


async def geocode_nominatim(location_str: str, sem: asyncio.Semaphore,
                             geocoder: Nominatim) -> dict | None:
    """
    Async wrapper around geopy Nominatim. Enforces 1 req/sec via semaphore + sleep.
    Returns location dict or None.
    """
    async with sem:
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: geocoder.geocode(location_str, addressdetails=True, language="en", timeout=10)
            )
            await asyncio.sleep(NOMINATIM_DELAY)
            if result is None:
                return None
            addr = result.raw.get("address", {})
            city = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("municipality")
            return {
                "city": city,
                "region": addr.get("state"),
                "country": addr.get("country"),
                "latitude": round(float(result.latitude), 6),
                "longitude": round(float(result.longitude), 6),
            }
        except (GeocoderTimedOut, GeocoderServiceError, Exception):
            return None


# -------------------------
# Networking (mirrors date.py)
# -------------------------

class RateLimiterPerHost:
    def __init__(self, max_per_host: int):
        self._semaphores = {}
        self._max = max_per_host

    def get(self, host: str) -> asyncio.Semaphore:
        if host not in self._semaphores:
            self._semaphores[host] = asyncio.Semaphore(self._max)
        return self._semaphores[host]


async def fetch_range_or_full(session: aiohttp.ClientSession, url: str):
    """
    Try Range GET for first 256 KB; fall back to full GET.
    Returns (bytes, status, headers) or (None, None, None) on error.
    """
    headers = DEFAULT_HEADERS | {"Range": f"bytes=0-{RANGE_BYTES}"}
    try:
        async with session.get(url, headers=headers) as resp:
            data = await resp.read()
            return data, resp.status, dict(resp.headers)
    except Exception:
        pass
    try:
        async with session.get(url, headers=DEFAULT_HEADERS) as resp:
            data = await resp.read()
            return data, resp.status, dict(resp.headers)
    except Exception:
        return None, None, None


# -------------------------
# Processing one row
# -------------------------

async def process_row(
    row: dict,
    session: aiohttp.ClientSession,
    per_host: RateLimiterPerHost,
    owm_sem: asyncio.Semaphore,
    nominatim_sem: asyncio.Semaphore,
    geocoder: Nominatim,
    nlp,
    api_key: str,
) -> dict:
    url = str(row.get("image_url") or "").strip()
    lightbox_id = row.get("lightbox_id")
    title = str(row.get("title") or "")
    host = urlparse(url).netloc
    sem = per_host.get(host)

    base_result = {
        "lightbox_id": lightbox_id,
        "city": None, "region": None, "country": None,
        "latitude": None, "longitude": None,
        "location_source": None,
    }

    # Step A1: fetch image and try metadata
    async with sem:
        img_bytes, status, _ = await fetch_range_or_full(session, url)

    if img_bytes:
        meta = extract_location_from_metadata(img_bytes)
        if meta:
            return {**base_result, **meta, "location_source": "metadata"}

    # Step A2: extract from title and geocode
    loc_str = extract_location_from_title(title, nlp)
    if loc_str:
        geo = await geocode_owm(loc_str, session, owm_sem, api_key)
        if geo is None:
            geo = await geocode_nominatim(loc_str, nominatim_sem, geocoder)
        if geo:
            return {**base_result, **geo, "location_source": "title"}

    return base_result


# -------------------------
# Main pipeline
# -------------------------

async def run(input_path: Path, out_csv: Path, api_key: str):
    print("Loading spaCy model...")
    nlp = spacy.load("en_core_web_sm")

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

    fieldnames = ["lightbox_id", "city", "region", "country", "latitude", "longitude", "location_source"]

    new_file = not out_csv.exists()
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    with out_csv.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if new_file:
            writer.writeheader()

        timeout = ClientTimeout(total=60, connect=10, sock_read=40)
        connector = aiohttp.TCPConnector(limit=GLOBAL_CONCURRENCY, ttl_dns_cache=300)
        geocoder = Nominatim(user_agent=NOMINATIM_USER_AGENT)

        async with aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
            raise_for_status=False,
        ) as session:
            per_host = RateLimiterPerHost(PER_HOST_LIMIT)
            owm_sem = asyncio.Semaphore(OWM_GEOCODING_CONCURRENCY)
            nominatim_sem = asyncio.Semaphore(1)
            sem_global = asyncio.Semaphore(GLOBAL_CONCURRENCY)
            buffer = []
            pbar = tqdm(total=len(rows), desc="Extracting locations", unit="img")

            async def worker(row):
                async with sem_global:
                    res = await process_row(row, session, per_host, owm_sem, nominatim_sem, geocoder, nlp, api_key)
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
