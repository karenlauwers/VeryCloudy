from pathlib import Path
import re 
from datetime import time

#-----------------------------------------
# PATHS 
#-----------------------------------------

# Project root
BASE = Path(__file__).resolve().parents[1] # parent[1] verwijst naar de parent van de parent van deze file config.py, dus de parent is verycloudy en daar de parent van is src
PROJECT_ROOT = BASE.parent # parent src, dus de VeryCloudy/

# Data directories
DATA_DIR = PROJECT_ROOT / "data"
IMAGE_DIR = PROJECT_ROOT / "images"
OUTPUT_DIR = PROJECT_ROOT / "output"
NOTEBOOK_DIR = PROJECT_ROOT / "notebooks"
SCRIPT_DIR = PROJECT_ROOT / "scripts"

# File paths 
FILEPATH_CLOUDS_CSV = DATA_DIR / "cloud_gallery.csv"
FILEPATH_CLOUDS_WITH_DATE = DATA_DIR / "cloud_gallery_with_date.csv"
FILEPATH_CLOUDS_WITH_DATE_LOC = DATA_DIR / "cloud_gallery_with_date_loc.csv"
FILEPATH_CLOUDS_WITH_DATE_LOC_WEATHER = DATA_DIR / "cloud_gallery_with_date_loc_weather.csv"
FILEPATH_CLOUDS_WITH_DATE_LOC_WEATHER_TYPE = DATA_DIR / "cloud_gallery_all_info.csv"
FILEPATH_CLOUDS_ALL_INFO_CLEAN = DATA_DIR / "cloud_gallery_all_info_clean.csv"
FILEPATH_NO_CLOUDS = DATA_DIR / "no_clouds.csv"

FILEPATH_FULL = DATA_DIR / "cloud_gallery_full.csv" # including no cloud rows

FILEPATH_DATE = DATA_DIR / "clouds_date.csv"
FILEPATH_LOCATION = DATA_DIR / "clouds_location.csv"
FILEPATH_WEATHER = DATA_DIR / "clouds_weather.csv"

FILEPATH_DATE_APPEND_CSV = DATA_DIR / "clouds_date_append.csv"

FILEPATH_CLOUDS_TEST = DATA_DIR / "cloud_gallery_testset.csv"
FILEPATH_CLOUDS_WITH_DATE_TESTSET = DATA_DIR / "cloud_gallery_with_date_testset.csv"
FILEPATH_CLOUDS_WITH_DATE_LOCATION_TESTSET = DATA_DIR / "cloud_gallery_with_date_location_testset.csv"
FILEPATH_CLOUDS_WITH_DATE_LOC_WEATHER_TESTSET = DATA_DIR / "cloud_gallery_with_date_loc_weather_testset.csv"
FILEPATH_CLOUDS_WITH_DATE_LOC_WEATHER_TYPE_TESTSET = DATA_DIR / "cloud_gallery_all_info_testset.csv"
FILEPATH_CLOUDS_ALL_INFO_CLEAN_TESTSET = DATA_DIR / "cloud_gallery_all_info_clean_testset.csv"
FILEPATH_FULL_TESTSET  = DATA_DIR / "cloud_gallery_full_testset.csv" # including no cloud rows

FILEPATH_LOCATION_TEST = DATA_DIR / "clouds_location_test.csv"
FILEPATH_WEATHER_TEST = DATA_DIR / "clouds_weather_test.csv"
FILEPATH_DATE_TEST = DATA_DIR / "clouds_date_test.csv"
FILEPATH_NO_CLOUDS_TEST = DATA_DIR / "no_clouds_test.csv"

FILEPATH_CLOUDS_JSON = DATA_DIR / "cloud_gallery.jsonl"
FILEPATH_JSON_CHECKPOINT = DATA_DIR / "cloud_gallery_checkpoint.jsonl"
FILEPATH_CSV_CHECKPOINT = DATA_DIR / "cloud_gallery_checkpoint.csv"
FILEPATH_CLOUDS_APPEND_CSV = DATA_DIR / "cloud_gallery_append.csv"
FILEPATH_CLOUDS_APPEND_JSON = DATA_DIR / "cloud_gallery_append.jsonl"
FILEPATH_JSON_CHECKPOINT2 = DATA_DIR / "cloud_gallery_checkpoint2.jsonl"
FILEPATH_CSV_CHECKPOINT2 = DATA_DIR / "cloud_gallery_checkpoint2.csv"

# URL for scraping
BASE_URL = "https://cloudappreciationsociety.org/"
GALLERY = f"{BASE_URL}/gallery/"
AJAX = f"{BASE_URL}/wp-admin/admin-ajax.php"


# --------------------------------
# Parameters for extracting date 
# --------------------------------
RANGE_BYTES = 262143  # fetch first 256 KB (0-262143 inclusive) from an image 
GLOBAL_CONCURRENCY = 12 # to not overload the server when fetching data from url 
PER_HOST_LIMIT = 4 # idem 
BATCH_FLUSH = 200 

EXIF_DT_RE = re.compile(r"^\d{4}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}$")

# Fallback: which time to use when only uploaded date exists
FALLBACK_TIME = time(hour=11, minute=0, second=0)

# If you want to treat fallback as UTC (e.g., for weather), set:
FALLBACK_IS_UTC = False  # set True to also emit UTC columns for fallback

DEFAULT_HEADERS = {
    "User-Agent": "CaptureDateExtractor/1.0 (+metadata-only; contact if needed)",
    "Accept": "*/*",
}

# --------------------------------
# Parameters for location extraction
# --------------------------------
OWM_GEOCODING_URL = "http://api.openweathermap.org/geo/1.0/direct"
NOMINATIM_USER_AGENT = "verycloudy/1.0 (thesis project)"
NOMINATIM_DELAY = 1.1   # seconds between calls — Nominatim ToS: max 1 req/sec
OWM_GEOCODING_CONCURRENCY = 10

# --------------------------------
# Parameters for weather extraction
# --------------------------------
OPEN_METEO_URL = "https://archive-api.open-meteo.com/v1/archive"
OPEN_METEO_CONCURRENCY = 3   # keep well under burst limit
OPEN_METEO_DELAY = 0.5       # ~6 req/s max across all workers

FILENAME_DATETIME_PATTERNS = [
    # 1) Start-of-name 14 digits: YYYYMMDDHHMMSS
    (re.compile(r'^(?P<ts>\d{14})'), "%Y%m%d%H%M%S"),

    # 2) Start-of-name YYYYMMDD[_-]?HHMMSS
    (re.compile(r'^(?P<date>\d{8})[_-]?(?P<time>\d{6})'), ("%Y%m%d", "%H%M%S")),

    # 3) Start-of-name YYYY-MM-DD[ T_-]?HH[:._-]MM[:._-]SS
    (re.compile(r'^(?P<date>\d{4}-\d{2}-\d{2})[T _-]?(?P<time>\d{2}[:._-]\d{2}[:._-]\d{2})'), ("%Y-%m-%d", "%H:%M:%S")),

    # 4) Start-of-name date only: YYYYMMDD
    (re.compile(r'^(?P<date>\d{8})'), ("%Y%m%d", None)),

    # 5) Start-of-name date only: YYYY-MM-DD
    (re.compile(r'^(?P<date>\d{4}-\d{2}-\d{2})'), ("%Y-%m-%d", None)),
]
