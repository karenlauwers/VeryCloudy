from verycloudy.config import RANGE_BYTES, GLOBAL_CONCURRENCY, PER_HOST_LIMIT, BATCH_FLUSH, FALLBACK_TIME, FALLBACK_IS_UTC, DEFAULT_HEADERS, FILENAME_DATETIME_PATTERNS, EXIF_DT_RE

import asyncio
import csv
import os
from pathlib import Path 
import sys
from io import BytesIO
from urllib.parse import urlparse, unquote as url_unquote
from datetime import datetime, time, timezone
import re
import pandas as pd

import aiohttp
from aiohttp import ClientTimeout
from PIL import Image, ExifTags
from PIL.ExifTags import TAGS
import exifread
from tqdm import tqdm

# -------------------------
# Helpers: datetime parsing
# -------------------------
def exif_dt_to_iso(dt_str: str) -> str | None:
    """EXIF 'YYYY:MM:DD HH:MM:SS' -> ISO 'YYYY-MM-DDTHH:MM:SS' (naive/local)."""
    if not dt_str or not isinstance(dt_str, str):
        return None
    s = dt_str.strip()
    if not EXIF_DT_RE.match(s):
        return None
    try:
        dt = datetime.strptime(s, "%Y:%m:%d %H:%M:%S")
        return dt.isoformat(timespec="seconds")
    except Exception:
        return None

def split_iso_to_date_time(iso: str) -> tuple[str | None, str | None]:
    """Split 'YYYY-MM-DDTHH:MM:SS' into ('YYYY-MM-DD','HH:MM:SS')."""
    if not iso or "T" not in iso:
        return (None, None)
    date_part, time_part = iso.split("T", 1)
    # strip timezone sign if present (we only expect naive here)
    if "+" in time_part:
        time_part = time_part.split("+")[0]
    if "Z" in time_part:
        time_part = time_part.replace("Z", "")
    return (date_part, time_part)

def xmp_iso_to_local_and_utc(dt_str: str) -> tuple[str | None, str | None]:
    """
    Parse XMP ISO-8601 (may include timezone).
    Returns (iso_local_or_naive, iso_utc).
    """
    if not dt_str:
        return (None, None)
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        iso_local = dt.replace(microsecond=0).isoformat()
        iso_utc = dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        return (iso_local, iso_utc)
    except Exception:
        return (None, None)
    
# ----------------------------------------------------
# Helpers: To extract date and/or time from filename
# ----------------------------------------------------
def normalize_time_separators(t: str) -> str:
    """Convert 09.49.38 or 09-49-38 to 09:49:38 for strptime."""
    return re.sub(r'[:._\-]', ':', t)

def parse_datetime_from_filename(url_or_path: str, fallback_time: time) -> tuple[str | None, str | None]:
    """
    Try to parse a capture datetime from the filename.
    Returns (iso_local_or_naive, source_label) or (None, None).
    """
    try:
        # extract and percent-decode the basename
        path = urlparse(url_or_path).path if '://' in url_or_path else url_or_path
        base = os.path.basename(path)
        base = url_unquote(base)

        # strip extension
        name = re.sub(r'\.[A-Za-z0-9]{1,5}$', '', base)

        for pat, fmt in FILENAME_DATETIME_PATTERNS:
            m = pat.search(name)
            if not m:
                continue

            # Case 1: single 14-digit timestamp
            if isinstance(fmt, str) and 'ts' in m.groupdict():
                ts = m.group('ts')
                dt = datetime.strptime(ts, fmt)
                return dt.replace(microsecond=0).isoformat(), "FILENAME:YYYYMMDDHHMMSS"

            # Case 2/3/4/5: date [+ optional time]
            if isinstance(fmt, tuple):
                date_fmt, time_fmt = fmt
                d = m.group('date')
                t = m.groupdict().get('time')

                if t and time_fmt:
                    t_norm = normalize_time_separators(t)
                    dt = datetime.strptime(f"{d} {t_norm}", f"{date_fmt} {time_fmt}")
                    return dt.replace(microsecond=0).isoformat(), "FILENAME:DATE+TIME"
                else:
                    # date only -> inject fallback_time (11:00:00)
                    dt_date = datetime.strptime(d, date_fmt).date()
                    dt = datetime.combine(dt_date, fallback_time)
                    return dt.replace(microsecond=0).isoformat(), "FILENAME:DATE_ONLY"

        return None, None
    except Exception:
        return None, None

# -------------------------
# EXIF/XMP extraction 
# -------------------------

# EXIF-data = written by the camera, date/time/location stamp from the camera 
# XMP-data = written by software to edit the image 

# check exif-data with Pillow-library, general purpose image library
def extract_exif_pillow(img_bytes: bytes) -> dict:
    out = {}
    try:
        with Image.open(BytesIO(img_bytes)) as im:
            exif = im.getexif()
            if exif:
                for k, v in exif.items():
                    tag = TAGS.get(k, k)
                    out[tag] = v
    except Exception:
        pass
    return out

# check exif-data with exifread-library, more robust, can handle cases that pillow cannot handle 
def extract_exif_exifread(img_bytes: bytes) -> dict:
    out = {}
    try:
        bio = BytesIO(img_bytes)
        tags = exifread.process_file(bio, details=False, strict=True)
        for k, v in tags.items():
            out[k] = str(v)
    except Exception:
        pass
    return out

# check xmp-data 
def extract_xmp_datetime(img_bytes: bytes) -> dict:
    """
    Parse embedded XMP packet (lightweight regex) for DateTimeOriginal/CreateDate.
    """
    result = {
        "xmp_dto_local": None, "xmp_dto_utc": None,
        "xmp_cd_local": None,  "xmp_cd_utc":  None
    }
    try:
        start = img_bytes.find(b"<x:xmpmeta")
        if start == -1:
            return result
        end = img_bytes.find(b"</x:xmpmeta>", start)
        if end == -1:
            return result
        xmp = img_bytes[start:end+12].decode("utf-8", errors="ignore")

        def _find(tag):
            m = re.search(rf"<\s*{tag}[^>]*>(.*?)</\s*{tag}\s*>", xmp,
                          flags=re.IGNORECASE | re.DOTALL)
            return m.group(1).strip() if m else None

        # Try common namespaces
        xmp_dto = _find(r"(?:exif:)?DateTimeOriginal")
        xmp_cd  = _find(r"(?:xmp:)?CreateDate") or _find(r"(?:photoshop:)?DateCreated")

        if xmp_dto:
            loc, utc = xmp_iso_to_local_and_utc(xmp_dto)
            result["xmp_dto_local"] = loc
            result["xmp_dto_utc"]   = utc
        if xmp_cd:
            loc, utc = xmp_iso_to_local_and_utc(xmp_cd)
            result["xmp_cd_local"] = loc
            result["xmp_cd_utc"]   = utc
    except Exception:
        pass
    return result

def choose_best_datetime(exif_p: dict, exif_e: dict, xmp: dict) -> tuple[str | None, str | None, str | None]:
    """
    Returns (date_taken_iso_local_or_naive, date_taken_iso_utc_or_none, source_field)
    Priority:
      1) EXIF DateTimeOriginal
      2) EXIF DateTimeDigitized/CreateDate
      3) EXIF DateTime
      4) XMP DateTimeOriginal
      5) XMP CreateDate
    """
    # Pillow EXIF first
    for key, label in [
        ("DateTimeOriginal", "EXIF:DateTimeOriginal"),
        ("DateTimeDigitized", "EXIF:CreateDate"),
        ("DateTime",         "EXIF:DateTime"),
    ]:
        val = exif_p.get(key)
        if isinstance(val, bytes):
            try: val = val.decode("utf-8", "ignore")
            except Exception: val = None
        if val:
            iso = exif_dt_to_iso(str(val))
            if iso:
                return (iso, None, label)

    # exifread keys
    for k, label in [
        ("EXIF DateTimeOriginal", "EXIF:DateTimeOriginal"),
        ("EXIF DateTimeDigitized", "EXIF:CreateDate"),
        ("Image DateTime", "EXIF:DateTime"),
    ]:
        if k in exif_e:
            iso = exif_dt_to_iso(exif_e[k])
            if iso:
                return (iso, None, label)

    # XMP with timezone (gives local and UTC)
    if xmp.get("xmp_dto_local"):
        return (xmp["xmp_dto_local"], xmp.get("xmp_dto_utc"), "XMP:DateTimeOriginal")
    if xmp.get("xmp_cd_local"):
        return (xmp["xmp_cd_local"], xmp.get("xmp_cd_utc"), "XMP:CreateDate")

    return (None, None, None)

# -------------------------
# Networking 
# -------------------------
class RateLimiterPerHost:
    def __init__(self, max_per_host: int):
        self._semaphores = {}
        self._max = max_per_host
    def get(self, host: str) -> asyncio.Semaphore:
        if host not in self._semaphores:
            self._semaphores[host] = asyncio.Semaphore(self._max)
        return self._semaphores[host]

async def head_last_modified(session: aiohttp.ClientSession, url: str):
    try:
        async with session.head(url, headers=DEFAULT_HEADERS, allow_redirects=True) as resp:
            return resp.status, dict(resp.headers)
    except Exception:
        return None, None

async def fetch_range_or_full(session: aiohttp.ClientSession, url: str):
    """
    Try Range GET for first 256 KB; fall back to full GET in memory.
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
# IO: CSV / JSONL
# -------------------------

def read_input(path: Path) -> pd.DataFrame:
    """
    Supports:
      - CSV with columns: lightbox_id, image_url, date_iso, ...
      - JSONL with same fields (one JSON per line)
    """
    ext = path.suffix.lower()
    if ext == ".jsonl":
        rows = []
        with path.open("r", encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if ln:
                    rows.append(pd.read_json(BytesIO((ln+"\n").encode("utf-8")), lines=True))
        df = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    else:
        df = pd.read_csv(path)
    if "url" in df.columns and "image_url" not in df.columns:
        df = df.rename(columns={"url": "image_url"})
    return df

def parse_uploaded_date(row) -> datetime | None:
    """
    Prefer date_iso (YYYY-MM-DD) if present; else try date_raw (e.g., 'December 23, 2025').
    """
    date_str = None
    if "date_iso" in row and pd.notna(row["date_iso"]):
        date_str = str(row["date_iso"]).strip()
        try:
            return datetime.strptime(date_str, "%Y-%m-%d")
        except Exception:
            pass
    if "date_raw" in row and pd.notna(row["date_raw"]):
        raw = str(row["date_raw"]).strip()
        for fmt in ["%B %d, %Y", "%d %B %Y", "%b %d, %Y"]:
            try:
                return datetime.strptime(raw, fmt)
            except Exception:
                continue
    return None

# -------------------------
# Processing one URL
# -------------------------
async def process_row(row: dict, session: aiohttp.ClientSession, per_host: RateLimiterPerHost):
    url = str(row.get("image_url") or row.get("url") or "").strip()
    lightbox_id = row.get("lightbox_id")
    host = urlparse(url).netloc
    sem = per_host.get(host)

    async with sem:
        # HEAD for server Last-Modified (not camera time, but useful to log)
        # head_status, head_headers = await head_last_modified(session, url)
        # server_last_modified = head_headers.get("Last-Modified") if head_headers else None

        # Range/GET bytes in memory
        img_bytes, status, headers = await fetch_range_or_full(session, url)
        if img_bytes is None or status is None or status in (404, 403):
            upl = parse_uploaded_date(row)
            if upl:
                dt_local = datetime.combine(upl.date(), FALLBACK_TIME)
                date_local, time_local = dt_local.strftime("%Y-%m-%d"), dt_local.strftime("%H:%M:%S")
                if FALLBACK_IS_UTC:
                    dt_utc = dt_local.astimezone(timezone.utc)
                    date_utc, time_utc = dt_utc.strftime("%Y-%m-%d"), dt_utc.strftime("%H:%M:%S")
                else:
                    date_utc, time_utc = None, None
            else:
                date_local = time_local = date_utc = time_utc = None
            
            http_msg = f"HTTP {status}" if status else "Network error"
            error_msg = f"{http_msg} + fallback to upload"

            return {
                "lightbox_id": lightbox_id, "image_url": url, "status": status or 0,
                "date_taken": date_local, "time_taken": time_local,
                "date_taken_utc": date_utc, "time_taken_utc": time_utc,
                "source_field": None, "fallback_used": True,
                "error": error_msg,
            }

        # Sanity: content-type looks like image or JPEG/PNG signature
        ctype = (headers or {}).get("Content-Type", "")
        if ("image" not in ctype.lower()) and (not img_bytes.startswith(b"\xff\xd8") and not img_bytes.startswith(b"\x89PNG")):
            # Just fallback to uploaded date
            upl = parse_uploaded_date(row)
            if upl:
                dt_local = datetime.combine(upl.date(), FALLBACK_TIME)
                date_local, time_local = dt_local.strftime("%Y-%m-%d"), dt_local.strftime("%H:%M:%S")
                if FALLBACK_IS_UTC:
                    dt_utc = dt_local.astimezone(timezone.utc)
                    date_utc, time_utc = dt_utc.strftime("%Y-%m-%d"), dt_utc.strftime("%H:%M:%S")
                else:
                    date_utc, time_utc = None, None
            else:
                date_local = time_local = date_utc = time_utc = None

            http_msg = f"Unsupported content-type: {ctype}"
            error_msg = f"{http_msg} + fallback to upload"

            return {
                "lightbox_id": lightbox_id, "image_url": url, "status": status,
                "date_taken": date_local, "time_taken": time_local,
                "date_taken_utc": date_utc, "time_taken_utc": time_utc,
                "source_field": None, "fallback_used": True,
                "error": error_msg
            }

        # Extract EXIF/XMP
        exif_p = extract_exif_pillow(img_bytes)
        exif_e = extract_exif_exifread(img_bytes)
        xmp = extract_xmp_datetime(img_bytes)

        date_iso_local, date_iso_utc, src = choose_best_datetime(exif_p, exif_e, xmp)

        if date_iso_local:
            date_local, time_local = split_iso_to_date_time(date_iso_local)
            if date_iso_utc:
                date_utc, time_utc = split_iso_to_date_time(date_iso_utc)
            else:
                date_utc, time_utc = None, None
            fallback_used = False
            error_msg = "capture in metadata" 

        else:
            # NEW: try filename-based extraction
            file_iso, file_src = parse_datetime_from_filename(url, FALLBACK_TIME)
            if file_iso:
                date_local, time_local = split_iso_to_date_time(file_iso)
                date_utc, time_utc = None, None  # filename has no timezone
                src = file_src
                fallback_used = False
                error_msg = "capture in filename"

            else:
                # Fallback to uploaded date at fixed time
                upl = parse_uploaded_date(row)
                if upl:
                    dt_local = datetime.combine(upl.date(), FALLBACK_TIME)
                    date_local, time_local = dt_local.strftime("%Y-%m-%d"), dt_local.strftime("%H:%M:%S")
                    if FALLBACK_IS_UTC:
                        dt_utc = dt_local.astimezone(timezone.utc)
                        date_utc, time_utc = dt_utc.strftime("%Y-%m-%d"), dt_utc.strftime("%H:%M:%S")
                    else:
                        date_utc, time_utc = None, None
                else:
                    date_local = time_local = date_utc = time_utc = None
                src = None
                fallback_used = True
                error_msg = "fallback to upload"

        return {
            "lightbox_id": lightbox_id, "image_url": url, "status": status,
            "date_taken": date_local, "time_taken": time_local,
            "date_taken_utc": date_utc, "time_taken_utc": time_utc,
            "source_field": src, "fallback_used": fallback_used,
            "error": error_msg
        }

# -------------------------
# Main pipeline
# -------------------------
async def run(input_path: Path, out_csv: Path):
    df = read_input(input_path)

    # If output exists, resume by skipping already processed image_ids (lightbox_id)
    processed_ids = set()
    if out_csv.exists():
        try:
            prev = pd.read_csv(out_csv)
            if "lightbox_id" in prev.columns:
                processed_ids = set(prev["lightbox_id"].astype(str).tolist())
        except Exception:
            pass

    # Build rows to process
    rows = []
    for _, r in df.iterrows():
        lightbox_id = str(r.get("lightbox_id", "")).strip()
        if lightbox_id and lightbox_id in processed_ids:
            continue
        rows.append(r.to_dict())

    fieldnames = [
        "lightbox_id","image_url","status",
        "date_taken","time_taken",
        "date_taken_utc","time_taken_utc",
        "source_field","fallback_used",
        "error"
    ]
  
    # Open output file 
    new_file = not out_csv.exists()
    # Ensure parent folder exists 
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    with out_csv.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if new_file:
            writer.writeheader()

        timeout = ClientTimeout(total=60, connect=10, sock_read=40)
        connector = aiohttp.TCPConnector(limit=GLOBAL_CONCURRENCY, ttl_dns_cache=300)


        async with aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
            raise_for_status=False
        ) as session:
            per_host = RateLimiterPerHost(PER_HOST_LIMIT)
            buffer = []
            pbar = tqdm(total=len(rows), desc="Extracting capture dates", unit="img")
            sem_global = asyncio.Semaphore(GLOBAL_CONCURRENCY)

            async def worker(row):
                async with sem_global:
                    res = await process_row(row, session, per_host)
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