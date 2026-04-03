# VeryCloudy

**Year 1 Data Science thesis project — Karen Lauwers**

VeryCloudy builds a cloud and weather intelligence system to predict which cloud types will occur at a specific location up to 3 days in advance.

The project has 4 phases:
1. Build the cloud database** (data acquisition + enrichment)
2. Build a UI for exploring the database
3. Build the prediction model (ML) (not for now)
4. Build a UI for cloud predictions (not for now)

---

## The dataset

The full dataset is at `dataset/cloud_gallery_full.csv`.

| Property | Value |
|---|---|
| Rows | ~31,000 |
| Columns | 48 |
| Cloud photo rows | ~26,000 (is_cloudy ≠ False) |
| No-cloud rows | ~5,000 (is_cloudy = False, synthetic from Open-Meteo) |
| Source | [Cloud Appreciation Society](https://cloudappreciationsociety.org) + Open-Meteo |

**Key columns:**

| Column | Description |
|---|---|
| `lightbox_id` | Unique photo ID — join key across all intermediate files |
| `image_url` | Direct URL to the photo |
| `date_taken`, `time_taken` | Capture date and time (local) |
| `datetime_source` | How the datetime was found: EXIF / XMP / FILENAME / fallback |
| `fallback_dt_used` | True when time is unknown (11:00 placeholder was used) |
| `city`, `region`, `country` | Location text |
| `latitude`, `longitude` | Decimal coordinates |
| `location_source` | How the location was found: metadata / title_regex / title_spacy / title_country |
| `temp`, `humidity`, `pressure`, `dew_point` | Weather at capture time (Open-Meteo) |
| `clouds`, `clouds_low`, `clouds_mid`, `clouds_high` | Cloud cover % (total + altitude layers) |
| `wind_speed`, `wind_gust`, `wind_deg` | Wind data |
| `weather_code` | WMO weather condition code |
| `rain_1h`, `snow_1h` | Precipitation in the past hour (mm) |
| `cloud_type1–3` | Up to 3 WMO cloud genera (cumulus, cirrus, …) |
| `subtype1–2` | Up to 2 cloud subtypes (cumulonimbus incus, cirrus fibratus, …) |
| `is_cloudy` | False for synthetic no-cloud rows |

> **Quality note:** Only rows where `datetime_source` contains EXIF, XMP, or FILENAME have a reliable capture time — and therefore a correctly matched weather observation. Rows where `fallback_dt_used = True` have weather data for 11:00 on the capture date, which may not reflect the actual conditions. For weather analysis, use `make_quality_df(df)` from `src/verycloudy/analysis.py`, which filters to quality rows + all no-cloud rows.

---

## Setup

### 1. Create the conda environment

```bash
conda env create -f environment.yml
conda activate very_cloudy
```

### 2. Install the package in editable mode

```bash
pip install -e .
```

### 3. Download the spaCy language model (one-time)

Required for location extraction from photo titles:

```bash
python -m spacy download en_core_web_sm
```

Or, if the above is blocked by your network:

```bash
pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.7.1/en_core_web_sm-3.7.1-py3-none-any.whl
```

---

## Run the Streamlit app

```bash
streamlit run app/app.py
```

The app loads `dataset/cloud_gallery_full.csv` and opens in your browser at `http://localhost:8501`.

**Tabs:**
- **Build** — how the dataset was assembled, step by step
- **Explore** — dataset overview: cloud types, countries, years, quality report
- **Look** — photo viewer with QR codes
- **Feel** — interactive weather analysis by location (uses quality data by default)
- **Learn** — cloud genera reference + weather parameter explanations

---

## Run the demo pipeline

The demo scrapes ~80 photos from the CAS gallery and runs the full 11-step pipeline end-to-end, producing a small version of the complete dataset.

### Prerequisites

1. **Browser session cookie** — log in to [cloudappreciationsociety.org](https://cloudappreciationsociety.org), open browser DevTools → Application → Cookies, and copy the cookie string. Paste it into `COOKIE = ""` at the top of the script.

2. **OWM API key (optional)** — an OpenWeatherMap API key speeds up geocoding. Without it, Nominatim is used (free but limited to 1 request/second). To use it, create a `.env` file at the project root:

```
OWM_API_KEY=your_key_here
```

### Run

```bash
python scripts/build_cloud_gallery_demo.py
```

Output files are written to `data/` with `_demo` suffixes. The final dataset lands at `data/cloud_gallery_full_demo.csv`.

> The script will refuse to run if any `_demo` output file already exists — delete them first to re-run.

---

## Project structure

```
VeryCloudy/
├── app/
│   └── app.py                  # Streamlit app
├── data/                       # Intermediate and test CSVs (pipeline outputs)
├── dataset/
│   └── cloud_gallery_full.csv  # Full dataset (ready to use)
├── images/                     # App header image
├── notebooks/
│   └── analysis.ipynb          # Exploratory analysis notebook
├── scripts/
│   ├── build_cloud_gallery_demo.py  # End-to-end demo pipeline (11 steps)
│   ├── scraping_by_api.py      # CAS gallery scraper (HTTP/JSON)
│   ├── scraping_by_selenium.py # Earlier Selenium scraper (deprecated)
│   ├── date.py                 # EXIF/XMP/filename datetime extraction
│   ├── location.py             # GPS metadata + NER geocoding
│   ├── weather.py              # Open-Meteo historical weather fetch
│   ├── cloudtype.py            # Cloud type/subtype classification from tags
│   ├── no_clouds.py            # Synthetic no-cloud row generation
│   ├── update.py               # Post-processing and cleanup
│   └── main_*.py               # Entry points for individual pipeline steps
├── src/verycloudy/
│   ├── analysis.py             # Analysis and chart functions (notebook)
│   ├── config.py               # All paths, constants, API settings
│   └── styling.py              # Matplotlib colour palette and style
├── environment.yml
├── pyproject.toml
└── tech_specs.md
```

---

## Github
https://github.com/karenlauwers/VeryCloudy 

## Data sources

- **[Cloud Appreciation Society](https://cloudappreciationsociety.org)** — cloud photos, titles, tags and author information. Used with respect for their rate limits.
- **[Open-Meteo](https://open-meteo.com)** — free historical weather API, no key required. Hourly data back to 1940.
- **[OpenWeatherMap Geocoding API](https://openweathermap.org/api/geocoding-api)** — optional, used to resolve place names to coordinates. Free tier is sufficient.
- **[Nominatim / OpenStreetMap](https://nominatim.org)** — free geocoding fallback (1 req/sec limit).

---

## Acknowledgements

Special thanks to the **Cloud Appreciation Society** for making their gallery publicly accessible, and to the photographers who submitted their cloud photos.