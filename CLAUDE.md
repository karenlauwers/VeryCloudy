# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**VeryCloudy** is a Data Science year 1 thesis project by Karen Lauwers. It builds a cloud and weather intelligence system to predict which cloud types will occur at specific locations up to 3 days in advance.

The project has 4 phases; currently working on **Part 1a** (data acquisition + enrichment):
1. Build the cloud database (data acquisition + enrichment) ← *current*
2. Build a UI for exploring the database
3. Build the prediction model (ML)
4. Build a UI for cloud predictions

## Environment Setup

```bash
# Conda environment (recommended)
conda env create -f environment.yml
conda activate verycloudy

# Install package in editable mode
pip install -e .

# Download spaCy language model (one-time, required for location extraction)
python -m spacy download en_core_web_sm
```

<!-- if this does not work (in my case the url was malformed by the cmd or powershell and I ran pip install commmand with actual github-url) -->
```bash 
pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.7.1/en_core_web_sm-3.7.1-py3-none-any.whl
```

## Running Scripts

```bash
python scripts/main_selenium.py    # Selenium-based scraper
python scripts/main_date.py        # Date/time extraction from EXIF metadata
```

## Testing

pytest is available. No test suite exists yet — ad-hoc testing is done via `notebooks/stuff.ipynb` and the `_testset` CSV files in `data/`.

## Architecture

### Data Pipeline (sequential, append-only)

| Step | Script | Output CSV | Status |
|------|--------|-----------|--------|
| Scrape CAS gallery | `scraping_by_selenium.py` / `scraping_by_api.py` | `cloud_gallery_testset.csv` | Done |
| Extract datetime | `date.py` / `main_date.py` | `clouds_date_testset.csv` | Done |
| Merge base file | — | `cloud_gallery_with_date_testset.csv` | Done ← *current input* |
| Extract location | TBD | `clouds_location_test.csv` | To do |
| Fetch weather | TBD | `clouds_weather.csv` | To do |
| Classify cloud types | TBD | new columns on base file | To do |

All scripts work from `data/cloud_gallery_with_date_testset.csv` as the current base input.

### Key Modules

- **[src/verycloudy/config.py](src/verycloudy/config.py)** — Central configuration: all paths, rate limits, data source URLs, EXIF datetime regex patterns, async concurrency settings (12 global / 4 per host), batch flush size (200 rows), fallback time (11:00 AM).
- **[scripts/scraping_by_api.py](scripts/scraping_by_api.py)** / **[scraping_by_selenium.py](scripts/scraping_by_selenium.py)** — Two scraping approaches for the Cloud Appreciation Society (CAS) gallery.
- **[scripts/date.py](scripts/date.py)** — Async EXIF/XMP/filename datetime extraction with rate limiting.

### Planned Enrichment (Part 1a — not yet implemented)

- **Location extraction:** GPS/IPTC/XMP from image metadata → fallback to NER + geocoding (spaCy + geopy/Nominatim) from `title` column → output: city, region, country, lat/lon.
- **Weather enrichment:** OpenWeatherMap historical API, keyed on `date_taken` + coordinates.
- **Cloud classification:** WMO genera (10 main types) and subtypes (30+ variants) extracted from `tags` column → new columns `cloud_type1–3`, `subtype1–2`.

### Tracking Key

`lightbox_id` is the join key across all CSV files. Always preserve it.

## Critical Constraints (from tech_specs.md)

- **Never overwrite existing CSV files** — all output goes to new files only.
- **Never delete any file.**
- All new data belongs in new CSVs; existing files are read-only inputs.
- Respect API and scraping rate limits conservatively (stay well under limits).
- Do not overload servers (CAS scraping or weather APIs).

## Agentic Workflow Convention

Per `tech_specs.md`, the expected workflow is:
1. User specifies what to implement.
2. Claude generates a plan/code for review (no execution yet).
3. User approves.
4. Claude executes (creating new CSVs only, never overwriting).
