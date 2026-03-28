# VeryCloudy — Technical Information Fiche (Part 1)

**Project:** Cloud & Weather Intelligence System
**Version:** Part 1 — Database foundation

---

## Table of Contents

- [VeryCloudy — Technical Information Fiche (Part 1)](#verycloudy--technical-information-fiche-part-1)
  - [Table of Contents](#table-of-contents)
  - [1. General Project Overview](#1-general-project-overview)
  - [2. Scope of Part 1 (Database Creation)](#2-scope-of-part-1-database-creation)
  - [3. Operational Constraints](#3-operational-constraints)
  - [4. Detailed Technical Specifications — Part 1a](#4-detailed-technical-specifications--part-1a)
    - [4.1 Base file (input)](#41-base-file-input)
    - [4.2 Task A — Create a file with location information](#42-task-a--create-a-file-with-location-information)
      - [Step A1 — Try reading location metadata from the image URL](#step-a1--try-reading-location-metadata-from-the-image-url)
      - [Step A2 — If no metadata: extract location from title](#step-a2--if-no-metadata-extract-location-from-title)
    - [4.3 Task B — Add historical weather information](#43-task-b--add-historical-weather-information)
    - [4.4 Task C — Extract cloud types and subtypes](#44-task-c--extract-cloud-types-and-subtypes)
  - [5. Agentic Engineering Guidelines](#5-agentic-engineering-guidelines)
  - [File Overview (after Part 1a)](#file-overview-after-part-1a)

---

## 1. General Project Overview

VeryCloudy is a cloud–weather intelligence system with the long‑term goal of predicting which types of clouds are likely to occur at a specific location up to 3 days in advance.

**Language used:** Python. See `requirements.txt` and `environment.yml` for packages and pip.

The full project consists of four parts:

- **Part 1. Build the cloud database**
  Collect and enrich cloud-image metadata: cloud properties, date/time, location, weather information.
- **Part 2. Build a UI for exploring the database**
  Users can ask: "Given weather X, what clouds are likely?" or "Given cloud Y, what weather is likely?"
- **Part 3. Build the prediction model**
  A ML model predicting probable cloud types at a given time/location.
- **Part 4. Build a UI for cloud predictions**
  Final interface for querying the prediction model.

Currently, we focus only on Part 1 and 2, beginning with Part 1. We only proceed to Part 2 if Part 1 is done.

---

## 2. Scope of Part 1 (Database Creation)

Part 1 builds the core CSV‑based database to be used in later stages. It is divided into:

**Part 1a: Data acquisition + enrichment**

- ✅ DONE — Cloud image scraping (CAS)
- ✅ DONE — Extract date & time
- ⬜ TO DO — Extract location
- ⬜ TO DO — Add weather information
- ⬜ TO DO — Identify cloud types & subtypes

**Part 1b: Simple user interface**

---

## 3. Operational Constraints

Your rules (must always be respected):

- Never overwrite any existing CSV file.
- Never delete any file.
- Keep working files during development period.
- All new data must be stored in new CSV files, unless explicitly stipulated otherwise.
- Always be sure of the `lightbox_id` to be able to merge files afterwards.
- Work only from: `data/cloud_gallery_with_date_testset.csv`
- Respect API rate limits more than required.
- Never overload servers (scraping or API).
- Metadata scraping from CAS images is allowed because you have explicit written permission.

---

## 4. Detailed Technical Specifications — Part 1a

Below is the cleaned, structured specification for all tasks required.

### 4.1 Base file (input)

`data/cloud_gallery_with_date_testset.csv`

Contains:

- `lightbox_id`
- image URL
- title
- tags
- date, time (merged earlier)

---

### 4.2 Task A — Create a file with location information

**Output file:** `data/clouds_location_test.csv`

**Goal:** For each image (row), extract:

| Column | Description |
|---|---|
| `lightbox_id` | Used to merge later files |
| `city` | string |
| `region` | string |
| `country` | string |
| `latitude` | float |
| `longitude` | float |
| `location_source` | `"metadata"` or `"title"` |

#### Step A1 — Try reading location metadata from the image URL

For each URL in the base file:

- Try to load the image headers and EXIF metadata.
- Look for:
  - GPS Latitude / Longitude
  - IPTC location fields
  - XMP location fields
- If found → fill `city`, `region`, `country`, `latitude`, `longitude`
- Set `location_source = "metadata"`.

Follow the slow iteration pattern in `scripts/date.py` (rate‑limiting behaviour reused).

#### Step A2 — If no metadata: extract location from title

If metadata access fails or has no location info:

- Extract location using:
  - Regex patterns (e.g. `", Spain"`)
  - OR spaCy Named Entity Recognition (GPE + LOC entities), use library en_core_web_sm, this is recommended. You must install this separately with pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.7.1/en_core_web_sm-3.7.1-py3-none-any.whl or with python -m spacy download en_core_web_sm, but then the url is formed by the cmd or powershell and in my case it was malformed and I used the pip install command.
- Send the extracted location string to a geocoding API.

**API priority order:**

1. **OpenWeatherMap Geocoding API**
   (Check if your student plan supports geocoding — if yes, use this first.)
2. **Fallback: geopy / Nominatim**
   (Free, open source, but strict rate limits — must respect them heavily.)
3. If neither works: leave location blank but keep row.

**Columns completed:**

- `city`
- `region`
- `country`
- `latitude`
- `longitude`
- `location_source = "title"`

---

### 4.3 Task B — Add historical weather information

**Output file:** `data/clouds_weather.csv`

**Input sources:**

- latitude & longitude (from location file)
- date & time (from base file)
- OpenWeatherMap (OWM) API

**API used:**

- ✔ OpenWeatherMap — One Call 3.0
- ✔ OpenWeatherMap — Historical data (if available in your student tier)

Make one request per row, rate‑limited well below OWM's limits.

**Output structure:**

| Column | Description |
|---|---|
| `lightbox_id` | For merging |
| all OWM weather fields | temperature, humidity, clouds, pressure, weather description, etc. |

---

### 4.4 Task C — Extract cloud types and subtypes

**Goal:** From `title` in the base file, check if there is one of the main primary cloud types. If there is, set this to column type1. If in the `title` there is one of the subtypes of clouds, set this to subtype2. Then, take a look at the column `tags` in the base file and go on for setting types and subtypes. Do not overwrite if you already set a type or subtype. Extract:

**Primary cloud types (max 3)**

From the official WMO 10 main genera:

- `cumulus`
- `stratocumulus`
- `stratus`
- `altostratus`
- `altocumulus`
- `cirrus`
- `cirrostratus`
- `cirrocumulus`
- `nimbostratus`
- `cumulonimbus`

**Columns to create directly in the base file (not a separate CSV):**

- `cloud_type1`
- `cloud_type2`
- `cloud_type3`

**Rules:**

- First match → `type1`
- Second match → `type2`
- Third match → `type3`

---

**Cloud subtypes (max 2)**

| | |
|---|---|
| `contrail` | `fibrates` |
| `fog` | `undulatus` |
| `virga` | `cap cloud` |
| `volutus` | `arcus` |
| `radiatus` | `cavum` |
| `mamma` | `tuba` |
| `lacunosus` | `lenticularis` |
| `pileus` | `noctilucent` |
| `nacreous` | `horseshoe vortex` |
| `fluctus` | `asperitas` |
| `uncinus` | `floccus` |
| `castellanus` | `distrail` |
| `pyrocumulus` | `congestus` |
| `velum` | `pannus` |
| `fractus` | `murus` |

**Columns to create:**

- `subtype1`
- `subtype2`

**Same rules:**

- First match → `subtype1`
- Second match → `subtype2`
- Ignore the rest.


** Update ** 
- Sometimes, there are subtypes without mention of a main type. 
- We will fix this by adding the most common main type for that subtype. We only choose 1 cloudtype - there may be more, but we won't take them into account. 
- We then add a column with "cloud_type_fix" = True, otherwise: false 
- Like this if subtype1 -> then cloud_type1: 
  - 'volutus'-> 'altocumulus'
  - 'arcus' -> 'cumulomimbus'
  - 'radiatus'-> 'cumulus'
  - 'cavum'-> 'altocumulus'
  - 'mamma'-> 'cumulonimbus'
  - 'tuba' -> 'cumulonimbus'
  - 'lacunosus' -> 'cirrocumulus'
  - 'lenticularis'-> 'altocumulus'
  - 'pileus' -> 'cumulus'
  - 'horsehoe vortex' -> 'cumulus'
  - 'fluctus'->'cirrus'
  - 'asperitas'-> 'stratocumulus'
  - 'uncinus'-> 'cirrus'
  - 'floccus' -> 'cirrus'
  - 'castellanus' -> 'altocumulus'
  - 'distrail' -> 'altocumulus'
  - 'contrail'-> 'cirrus'
  - 'pyrocumulus'-> 'cumulus'
  - 'congestus'->'cumulus'
  - 'velum' -> 'cumulus'
  - 'pannus' -> 'cumulonimbus'
  - 'fractus' -> 'cumulus'
  - 'murus'-> 'cumulonimbus'
  - 'virga' -> 'altostratus'
  - 'fog' -> 'stratus'
  - 'fibrates' -> 'cirrus'
  - 'undulatus' -> 'altocumulus'
  - 'cap cloud' -> 'stratus'

---

## 5. Agentic Engineering Guidelines

To keep you fully in control, your workflow for later steps should be:

1. You tell me what step you want me to help implement.
2. I generate the plan or code, but do not run it until you approve.
3. You verify.
4. If approved, I execute via Python (creating new CSV files only).
5. Results are saved as new files — never overwriting existing ones.

This ensures: full transparency, reproducibility, zero destructive operations, and no loss of your carefully prepared base file.

---

## File Overview (after Part 1a)

| File | Purpose | Status |
|---|---|---|
| `cloud_gallery_testset.csv` | Raw scraper output | ✅ Done |
| `clouds_date_testset.csv` | Extracted datetime | ✅ Done |
| `cloud_gallery_with_date_testset.csv` | Merged base file | ✅ Done |
| `clouds_location_test.csv` | Location extraction | ⬜ To do |
| `clouds_weather.csv` | Weather extraction | ⬜ To do |
| *(columns added to base file)* | `cloud_type1–3` + `subtype1–2` | ⬜ To do |

