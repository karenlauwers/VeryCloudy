"""
VeryCloudy — Streamlit App (Part 1b)

Tabs:
  1. Explorer     — analysis charts with interactive filters
  2. Photos       — photo viewer + QR code + link
  3. Weather      — boxplots by region + cloud type
  4. Cloud Info   — cloud genera + weather parameter reference

Run with (from project root):
    streamlit run app/app.py

Requires:
    pip install streamlit qrcode[pil] plotly pycountry
"""

import sys
from pathlib import Path

import folium
import pandas as pd
import plotly.express as px
import qrcode
import streamlit as st
from folium import Circle, Marker
from PIL import Image
from streamlit_folium import st_folium

# Make src/ importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from verycloudy.config import FILEPATH_DATASET_TO_SHARE
from verycloudy.styling import CLOUD_TYPE_COLORS
from verycloudy.analysis import data_quality_report, make_quality_df

# ──────────────────────────────────────────────────────────
# Page config
# ──────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Very Cloudy__",
    layout="wide",
)

# ── Header background image ──────────────────────────────
import base64
_img_path = Path(__file__).resolve().parent.parent / "images" / "app_catcher1.jpg"
if _img_path.exists():
    with open(_img_path, "rb") as _f:
        _img_b64 = base64.b64encode(_f.read()).decode()
    st.markdown(
        f"""
        <div style="
            background-image: url('data:image/jpeg;base64,{_img_b64}');
            background-size: cover;
            background-position: center 40%;
            border-radius: 12px;
            padding: 48px 40px 32px 40px;
            margin-bottom: 16px;
        ">
            <h1 style="color:white;text-shadow:1px 2px 6px rgba(0,0,0,0.7);
                       font-size:2.8rem;margin:0;">Very Cloudy__</h1>
            <p style="color:#e8f4ff;text-shadow:1px 1px 4px rgba(0,0,0,0.6);
                      font-size:1.1rem;margin:4px 0 0 0;">
                With special thanks to the <a href="https://cloudappreciationsociety.org"
                style="color:#e8f4ff;">Cloud Appreciation Society</a>
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

# ──────────────────────────────────────────────────────────
# Data loading
# ──────────────────────────────────────────────────────────
import pycountry

_FULL_TO_CODE = {c.name.lower(): c.alpha_2 for c in pycountry.countries}
_FULL_TO_CODE.update({
    "united states": "US", "usa": "US", "u.s.": "US",
    "united kingdom": "GB", "uk": "GB", "great britain": "GB",
    "netherlands": "NL", "the netherlands": "NL",
    "ireland": "IE", "republic of ireland": "IE",
})

def _to_country_name(val) -> str:
    if pd.isna(val) or str(val).strip() == "":
        return ""
    v = str(val).strip()
    if len(v) == 2:
        c = pycountry.countries.get(alpha_2=v.upper())
        return c.name if c else v
    code = _FULL_TO_CODE.get(v.lower())
    if code:
        c = pycountry.countries.get(alpha_2=code)
        return c.name if c else v
    return v


@st.cache_data
def load_data() -> pd.DataFrame:
    df = pd.read_csv(FILEPATH_DATASET_TO_SHARE, low_memory=False)
    df["year"] = pd.to_datetime(df["date_taken"], errors="coerce").dt.year
    # Drop rows with clearly bad years (CAS founded 2004 — anything earlier is a faulty EXIF date)
    df = df[df["year"].isna() | (df["year"] >= 2004)]
    if "is_cloudy" in df.columns:
        df["is_cloudy"] = df["is_cloudy"].fillna(True).astype(bool)
        mask_no_cloud = ~df["is_cloudy"] & df["cloud_type1"].isna()
        mask_unclassified = df["is_cloudy"] & df["cloud_type1"].isna()
        df.loc[mask_no_cloud, "cloud_type1"] = "no cloud"
        df.loc[mask_unclassified, "cloud_type1"] = "unclassified"
    else:
        df["cloud_type1"] = df["cloud_type1"].fillna("unclassified")
    for col in ("latitude", "longitude"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["country_name"] = df["country"].apply(_to_country_name)
    return df


df_all = load_data()

CLOUD_TYPES = sorted([t for t in df_all["cloud_type1"].dropna().unique() if t != "unclassified"])
COUNTRIES   = sorted(df_all["country_name"].dropna().replace("", pd.NA).dropna().unique().tolist())
YEAR_MIN    = int(df_all["year"].min()) if df_all["year"].notna().any() else 2005
YEAR_MAX    = int(df_all["year"].max()) if df_all["year"].notna().any() else 2026

WEATHER_PARAMS = {
    "Temperature (°C)":      "temp",
    "Feels like (°C)":       "feels_like",
    "Humidity (%)":          "humidity",
    "Dew point (°C)":        "dew_point",
    "Pressure (hPa)":        "pressure",
    "Cloud cover (%)":       "clouds",
    "Cloud cover low (%)":   "clouds_low",
    "Cloud cover mid (%)":   "clouds_mid",
    "Cloud cover high (%)":  "clouds_high",
    "Wind speed (km/h)":     "wind_speed",
    "Wind gust (km/h)":      "wind_gust",
    "Rain 1h (mm)":          "rain_1h",
}

# Feel tab params — no feels_like, no low/mid/high cloud cover, add temp−dewpoint diff
FEEL_PARAMS = {
    "Temperature (°C)":           "temp",
    "Humidity (%)":               "humidity",
    "Dew point (°C)":             "dew_point",
    "Temp − Dew point (°C)":      "_tdp_diff",
    "Pressure (hPa)":             "pressure",
    "Cloud cover (%)":            "clouds",
    "Wind speed (km/h)":          "wind_speed",
    "Wind gust (km/h)":           "wind_gust",
    "Rain 1h (mm)":               "rain_1h",
}

# ──────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────
def apply_filters(
    df: pd.DataFrame,
    cloud_types: list,
    subtypes: list,
    countries: list,
    year_range: tuple,
) -> pd.DataFrame:
    mask = pd.Series(True, index=df.index)
    if cloud_types:
        mask &= df["cloud_type1"].isin(cloud_types)
    if subtypes:
        mask &= df["subtype1"].isin(subtypes)
    if countries:
        mask &= df["country_name"].isin(countries)
    year_mask = df["year"].between(year_range[0], year_range[1]) | df["year"].isna()
    mask &= year_mask
    return df[mask]


def bounding_box_filter(df: pd.DataFrame, lat: float, lon: float, radius_km: float) -> pd.DataFrame:
    deg = radius_km / 111.0
    return df[
        df["latitude"].between(lat - deg, lat + deg) &
        df["longitude"].between(lon - deg, lon + deg)
    ]


@st.cache_data(show_spinner=False)
def geocode_name(name: str):
    """Returns (lat, lon, display_name) or None."""
    try:
        from geopy.geocoders import Nominatim
        geolocator = Nominatim(user_agent="verycloudy/1.0")
        loc = geolocator.geocode(name, timeout=10)
        if loc:
            return loc.latitude, loc.longitude, loc.address
    except Exception:
        pass
    return None


@st.cache_data(show_spinner=False)
def reverse_geocode(lat: float, lon: float) -> str:
    """Returns a place name string for coordinates, or empty string."""
    try:
        from geopy.geocoders import Nominatim
        geolocator = Nominatim(user_agent="verycloudy/1.0")
        loc = geolocator.reverse((lat, lon), timeout=10, language="en")
        if loc:
            # Return city + country
            addr = loc.raw.get("address", {})
            parts = [
                addr.get("city") or addr.get("town") or addr.get("village") or addr.get("county", ""),
                addr.get("country", ""),
            ]
            return ", ".join(p for p in parts if p)
    except Exception:
        pass
    return ""


def make_qr(url: str) -> Image.Image:
    qr = qrcode.QRCode(box_size=4, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").convert("RGB")


def ct_color(cloud_type: str) -> str:
    return CLOUD_TYPE_COLORS.get(str(cloud_type).lower(), "#888888")


# ──────────────────────────────────────────────────────────
# Sidebar — shared filters
# ──────────────────────────────────────────────────────────
st.sidebar.title("Very Cloudy__")
st.sidebar.markdown("---")

sel_cloud_types = st.sidebar.multiselect(
    "Cloud type", CLOUD_TYPES, default=[],
    placeholder="All types",
)

# Subtypes available depend on selected cloud types
if sel_cloud_types:
    _df_for_subtypes = df_all[df_all["cloud_type1"].isin(sel_cloud_types)]
else:
    _df_for_subtypes = df_all
SUBTYPES_AVAILABLE = sorted(
    _df_for_subtypes["subtype1"].dropna().unique().tolist()
)
sel_subtypes = st.sidebar.multiselect(
    "Subtype", SUBTYPES_AVAILABLE, default=[],
    placeholder="All subtypes",
)

sel_countries = st.sidebar.multiselect(
    "Country", COUNTRIES, default=[],
    placeholder="All countries",
)
sel_years = st.sidebar.slider(
    "Year range", YEAR_MIN, YEAR_MAX, (YEAR_MIN, YEAR_MAX)
)

df_filtered = apply_filters(df_all, sel_cloud_types, sel_subtypes, sel_countries, sel_years)
st.sidebar.markdown("---")
st.sidebar.markdown(f"**{len(df_filtered):,}** observations selected")
st.sidebar.markdown(f"*(from {len(df_all):,} total)*")
st.sidebar.markdown("---")
st.sidebar.caption("Special thanks to the [Cloud Appreciation Society](https://cloudappreciationsociety.org) for the data.")
st.sidebar.markdown("---")
st.sidebar.caption("*Filters above apply to Explore, Look and Learn tabs only. The Feel tab has its own location-based controls.*")


# ──────────────────────────────────────────────────────────
# Tabs
# ──────────────────────────────────────────────────────────
st.markdown("""
<style>
    .stTabs [data-baseweb="tab"] {
        font-size: 1.3rem;
        font-weight: 600;
        padding: 10px 24px;
    }
</style>
""", unsafe_allow_html=True)

tab_build, tab1, tab2, tab3, tab4 = st.tabs([
    "Build", "Explore", "Look", "Feel", "Learn"
])


# ══════════════════════════════════════════════════════════
# TAB BUILD — How the dataset was built
# ══════════════════════════════════════════════════════════
with tab_build:
    st.header("How the dataset was built")
    st.markdown(
        "This dataset was assembled from scratch as part of a Data Science thesis. "
        "The goal: collect cloud photos, enrich them with location and weather data, "
        "and build a dataset that can train a model to predict cloud types 3 days in advance. "
        "Below is the full pipeline."
    )

    st.markdown("---")

    st.subheader("Web Scraping")
    st.markdown(
        "The basic idea was to build a dataset from the [Cloud Appreciation Society](https://cloudappreciationsociety.org) gallery. "
        "I asked for & got permission from the organisation to scrape their website. I worked at very slow pace rate to not overload the website. "
        "The first scraping attempts used **Selenium** to automate a real browser session on the website. "
        "It worked for small tests but turned out too brittle for a full-scale collection: "
        "any slow page load or session timeout broke the run. "
        "I found another way to srape the website: via direct **API approach** (HTTP requests to the gallery's JSON endpoint). "
        "This was not too complex: the CAS-website is a common WorldPress-website and the API-approach proved to be far more stable. "
        "This approach was used to scrape all cloud photos and information from the website. I repeated 2 times after a few weeks to collect new information. "
    )

    st.markdown("---")
    st.subheader("Pipeline — 11 steps")

    _steps = [
        (
            "Step 1 — Scrape the CAS gallery",
            "scraping_by_api.py",
            "main_scraping.py",
            "cloud_gallery.csv",
            "Send HTTP requests to the Cloud Appreciation Society gallery API, page by page. ",
            "Each photo yields a lightbox ID, title, author, image URL, tags, and a link to the full page. ",
            "The **lightbox_id** is the join key used throughout the entire pipeline.",
        ),
        (
            "Step 2 — Extract date and time",
            "date.py",
            "main_date.py",
            "clouds_date.csv",
            "To get date and time of the spotted cloud, tried to get information from:  \n",
            "**Preferred**: EXIF DateTimeOriginal (1st), XMP date tags (2nd)  \n",
            "**Otherwise**: date and time pattern in filename  \n", 
            "**Fallback**: date (upload date) and/or time (11 am)  \n",
            "To get EXIF-data: fetch from each image its first 256 KB via a Range request and read EXIF/XMP metadata. This works for newer images.", 
            "If none found, a fallback time of 11:00 is used and **fallback_dt_used** is flagged. ", 
            "Only rows with a real datetime are considered quality data for weather analysis.",
        ),
        (
            "Step 3 — Merge scrape and date",
            "-",
            "-",
            "Result in cloud_gallery_with_date.csv",
            "Merged the result files cloud_gallery and date manually. ",
            "Left-join the scrape file and the date file on **lightbox_id**. ", 
            "All photo rows are kept; the date columns are added where available.",
        ),
        (
            "Step 4 — Extract location",
            "location.py",
            "main_location.py",
            "clouds_location.csv",
            "To get the location of the spotted cloud, tried to get information from:  \n", 
            "**Preferred:** read GPS coordinates from EXIF/IPTC/XMP metadata embedded in the image.  \n", 
            "**Fallback:** parse the photo title with regex patterns and spaCy NER to find a place name,  \n",
            "then geocode it via the OpenWeatherMap Geocoding API (if a key is available) or Nominatim to get latitude and longitude.",
        ),
        (
            "Step 5 — Merge with location",
            "-",
            "-",
            "cloud_gallery_with_date_loc.csv ",
            "Merged the result files cloud_gallery_with_date and location manually. ",
            "Left-join the previous file with the location output on **lightbox_id**. ", 
            "Adds city, region, country, latitude and longitude.",
        ),
        (
            "Step 6 — Fetch historical weather information",
            "weather.py", 
            "main_weather.py",
            "clouds_weather.csv ",
            "For each row that has coordinates and a date, query the **Open-Meteo** historical weather API. ", 
            "In the first attempts, I worked with Open Weather Map (OWM) - from which I got a student API key. But the possibilities for historical info were to limited. ", 
            "Then I tried Open-Meteo, which is free and covers hourly data back to 1940. ", 
            "Working with Open-Meteo is limited as well: 10.000 API calls per day, 5.000 per hour and 600 per minute.", 
            "Time limits work with a rolling window, looking back at the past 60 minutes. ", 
            "To finish the rows of the dataset in a considerable amount of time, I ran the code several times, using different IP-addresses by using mobile hotspots of my family members.", 
            "Important issue is the exact time for wich the weather data have to be fetched:  \n", 
            "Open Meteo works with UTC-time. But we have mostly local naive time (from EXIF or filename) or fallbacktime or rarely XMP-time.  \n", 
            "Strategy used:  \n", 
            "**If XMP-time:** this is UTC time, use UTC time  \n", 
            "**If EXIF or filename**: this is local time, convert to UTC time  \n", 
            "**If fallbacktime**: this is a fictive time, treat as UTC time  \n", 
            "Returns temperature, humidity, pressure, dew point, wind, cloud cover levels, precipitation and weather code ", 
            "for the exact hour and location of the photo.",

        ),
        (
            "Step 7 — Merge with weather",
            "-", 
            "-", 
            "cloud_gallery_with_date_loc_weather.csv",
            "Merged the result of cloud_gallery_with_date_loc and the weather information manually. ",
            "Left-join with the weather output on **lightbox_id**. ",
            "All weather columns are added; rows without coordinates or date simply have NaN weather values.",
        ),
        (
            "Step 8 — Extract cloud types from title or tags",
            "cloudtype.py",
            "main_cloudtype.py",
            "cloud_gallery_all_info.csv",
            "Most CAS photos have community-submitted information on the cloud (sub)type in the title or the tags. ",
            "A rule-based classifier maps these tags to the 10 WMO cloud genera (cumulus, cirrus, …) ",
            "and up to 30+ subtypes (cumulonimbus incus, cirrus fibratus, …).  \n",
            "Up to 3 cloud types and 2 subtypes are extracted per photo. ",
            "First, we look at the title, then at the tags. First type encountered is filled in in the first column etc. ",
            "If a cloud (sub)type is filled in, it is never overwritten. If there are more than 3 types or 2 subtypes mentioned, they are not taken in account.",
        ),
        (
            "Step 9 — Post-processing and cleanup",
            "update.py", 
            "main_update.py",
            "cloud_gallery_all_info_clean.csv",
            "**Column renames:** especially with date and time settings, there are columns with same names, set throughout the process - changed the names to clarify their reason of existence  \n", 
            "**Reverse geocoding**: when the location is found by metadata of the image, there is no human readable information on city, region, country. Code to fix this.   \n", 
            "**Subtype fallback logic**: there are images that have a cloud subtype, but not main type. Most subtypes are a special form of a certain main type. Code to fix this.",
        ),
        (
            "Step 10 — Generate no-cloud rows",
            "no_clouds.py",
            "main_no_clouds.py",
            "no_clouds.csv ",
            "The model needs a **negative class**: observations where the sky is clear.  \n",
            "Clear-sky weather data is sampled from Open Meteo:  \n",
            "**Location**: randomly chosen from real locations in the dataset. Each location can generate max 3 rows with no-cloud information (to guarantee spread)  \n",
            "**Date**: randomly chosen  \n", 
            "Looking for Open Meteo reporting 0% cloud cover and fetching the relevant weather information. ", 
            "Built a file with the same columns as the basic dataset, to be able to concatenate them together. ", 
            "These synthetic rows get **is_cloudy = False** and no image URL.",
        ),
        (
            "Step 11 — Concatenate into the final dataset",
            "-",
            "-",
            "cloud_gallery_full.csv ",
            "Manually concatenated the updated cloud_gallery_all_info_clean with the no_clouds.",
            "The cleaned cloud photo rows and the synthetic no-cloud rows are concatenated. ", 
            "This is the dataset explored in the analysis and in this app.",
        ),
    ]

    for step in _steps:
        title, script, run, output = step[0], step[1], step[2], step[3]
        description = " ".join(step[4:])
        with st.expander(title):
            col_a, col_b = st.columns([4, 1])
            with col_a:
                st.markdown(description)
            with col_b:
                st.markdown(f"**Script:** `{script}`")
                st.markdown(f"**Run**: `{run}`")
                st.markdown(f"**Output:** `{output}`")

    st.markdown("---")
    st.subheader("Try it yourself")
    st.markdown(
        "The full pipeline above runs on the complete dataset. "
        "A demo version that runs all 11 steps on **~80 photos** is included in the repository:"
    )
    st.code("python scripts/build_cloud_gallery_demo.py", language="bash")
    st.caption(
        "Requirements: a browser session cookie from cloudappreciationsociety.org (free account). "
        "An OpenWeatherMap API key is optional — without it, geocoding falls back to Nominatim."
    )


# ══════════════════════════════════════════════════════════
# TAB 1 — Explorer
# ══════════════════════════════════════════════════════════
with tab1:
    st.header("Dataset Explorer")

    if df_filtered.empty:
        st.info("No data matches the current filters.")
    else:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Observations", f"{len(df_filtered):,}")
        m2.metric("Cloud types", df_filtered["cloud_type1"].nunique())
        m3.metric("Countries", df_filtered["country_name"].nunique())
        years_span = int(df_filtered["year"].max() - df_filtered["year"].min()) + 1
        m4.metric("Years covered", years_span)

        with st.expander("Data quality report", expanded=False):
            st.caption(
                "Quality report runs on the **full dataset** (sidebar filters not applied), "
                "so the counts are always consistent."
            )
            qr_df = data_quality_report(df_all)
            # Show as a clean table (suppress the printed version — we display it ourselves)
            st.dataframe(
                qr_df[qr_df["count"] != ""].rename(
                    columns={"check": "Check", "count": "Count", "note": "Note"}
                ),
                hide_index=True,
                use_container_width=True,
            )

        st.markdown("---")

        # Row 1: main cloud type + subtype side by side
        col_ct, col_st = st.columns(2)

        with col_ct:
            st.subheader("Observations per main cloud type")
            ct_counts = (
                df_filtered["cloud_type1"]
                .value_counts()
                .reset_index()
                .rename(columns={"cloud_type1": "Cloud type", "count": "Count"})
            )
            ct_counts = ct_counts[ct_counts["Cloud type"] != "unclassified"]
            no_cloud_row = ct_counts[ct_counts["Cloud type"] == "no cloud"]
            ct_counts = pd.concat([
                no_cloud_row,
                ct_counts[ct_counts["Cloud type"] != "no cloud"].iloc[::-1],
            ], ignore_index=True)
            fig_ct = px.bar(
                ct_counts, x="Count", y="Cloud type", orientation="h",
                color="Cloud type",
                color_discrete_map=CLOUD_TYPE_COLORS,
                labels={"Cloud type": "", "Count": "# observations"},
            )
            fig_ct.update_traces(width=0.8)
            fig_ct.update_layout(
                showlegend=False,
                height=max(300, len(ct_counts) * 38),
                margin=dict(l=0, r=20, t=10, b=40),
                bargap=0.1,
            )
            st.plotly_chart(fig_ct, width="stretch")

        with col_st:
            st.subheader("Observations per subtype")
            st_counts = (
                df_filtered["subtype1"]
                .dropna()
                .value_counts()
                .reset_index()
                .rename(columns={"subtype1": "Subtype", "count": "Count"})
            )
            if st_counts.empty:
                st.caption("No subtype data for the current selection.")
            else:
                st_counts = st_counts.iloc[::-1].reset_index(drop=True)
                fig_st = px.bar(
                    st_counts, x="Count", y="Subtype", orientation="h",
                    labels={"Subtype": "", "Count": "# observations"},
                )
                fig_st.update_traces(width=0.8, marker_color="#7B9EC8")
                fig_st.update_layout(
                    showlegend=False,
                    height=max(300, len(st_counts) * 28),
                    margin=dict(l=0, r=20, t=10, b=40),
                    bargap=0.1,
                )
                st.plotly_chart(fig_st, width="stretch")

        # Row 2: year + countries
        col_a, col_b = st.columns(2)

        with col_a:
            st.subheader("Observations per year")
            yr = df_filtered.groupby("year").size().reset_index(name="Count")
            fig_yr = px.bar(yr, x="year", y="Count",
                            labels={"year": "Year", "Count": "# observations"})
            fig_yr.update_traces(marker_color="#5B7FA6")
            fig_yr.update_layout(height=400, margin=dict(l=0, r=20, t=10, b=40))
            st.plotly_chart(fig_yr, width="stretch")

        with col_b:
            st.subheader("Top 15 countries")
            top_c = (
                df_filtered["country_name"]
                .replace("", pd.NA).dropna()
                .value_counts()
                .head(15)
                .reset_index()
                .rename(columns={"country_name": "Country", "count": "Count"})
            )
            top_c = top_c.iloc[::-1].reset_index(drop=True)
            fig_co = px.bar(top_c, x="Count", y="Country", orientation="h",
                            labels={"Country": "", "Count": "# observations"})
            fig_co.update_traces(width=0.8, marker_color="#5B7FA6")
            fig_co.update_layout(height=400, margin=dict(l=0, r=20, t=10, b=40), bargap=0.1)
            st.plotly_chart(fig_co, width="stretch")

        # Row 3: day of week + month of year
        col_dow, col_mon = st.columns(2)

        with col_dow:
            st.subheader("Observations per day of week")
            _dow_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            dow = (
                pd.to_datetime(df_filtered["date_taken"], errors="coerce")
                .dt.day_name()
                .value_counts()
                .reindex(_dow_order, fill_value=0)
                .reset_index()
                .rename(columns={"index": "Day", "day_name": "Day", "count": "Count"})
            )
            dow.columns = ["Day", "Count"]
            fig_dow = px.bar(dow, x="Day", y="Count",
                             labels={"Day": "", "Count": "# observations"})
            fig_dow.update_traces(marker_color="#5B7FA6")
            fig_dow.update_layout(height=350, margin=dict(l=0, r=20, t=10, b=40))
            st.plotly_chart(fig_dow, width="stretch")

        with col_mon:
            st.subheader("Observations per month")
            _mon_order = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
            mon = (
                pd.to_datetime(df_filtered["date_taken"], errors="coerce")
                .dt.month
                .value_counts()
                .sort_index()
                .reset_index()
                .rename(columns={"index": "month", "month": "month", "count": "Count"})
            )
            mon.columns = ["month", "Count"]
            mon["Month"] = mon["month"].apply(lambda m: _mon_order[m - 1])
            fig_mon = px.bar(mon, x="Month", y="Count",
                             category_orders={"Month": _mon_order},
                             labels={"Month": "", "Count": "# observations"})
            fig_mon.update_traces(marker_color="#5B7FA6")
            fig_mon.update_layout(height=350, margin=dict(l=0, r=20, t=10, b=40))
            st.plotly_chart(fig_mon, width="stretch")


# ══════════════════════════════════════════════════════════
# TAB 2 — Photos
# ══════════════════════════════════════════════════════════
with tab2:
    st.header("Cloud Photo Viewer")

    df_photos = df_filtered[
        df_filtered["image_url"].notna() &
        (df_filtered["image_url"].astype(str).str.startswith("http"))
    ]

    if df_photos.empty:
        st.info("No photos match the current filters.")
    else:
        st.markdown(f"*{len(df_photos):,} matching photos — showing random samples*")

        col_n, col_btn = st.columns([1, 1])
        with col_n:
            n_show = st.slider("Number of photos to show", 1, 5, 3, key="photo_n")
        with col_btn:
            st.markdown(" ")
            st.markdown(" ")
            shuffle = st.button("🔀 New selection")

        if shuffle or "photo_seed" not in st.session_state:
            import random
            st.session_state["photo_seed"] = random.randint(0, 999999)

        sample = df_photos.sample(
            min(n_show, len(df_photos)),
            random_state=st.session_state["photo_seed"]
        )

        for _, row in sample.iterrows():
            st.markdown("---")
            c_img, c_qr = st.columns([3, 1])

            with c_img:
                st.markdown(f"**{row.get('title', 'Untitled')}**")
                st.caption(
                    f"{row.get('author_name', '')} · "
                    f"{row.get('date_taken', '—')} · "
                    f"{row.get('city', '')} {row.get('country', '')}"
                )
                try:
                    st.image(str(row["image_url"]), width=500)
                except Exception:
                    st.warning("Image could not be loaded.")
                ct1 = row.get("cloud_type1", "unclassified") or "unclassified"
                st1 = row.get("subtype1", "—")
                st2 = row.get("subtype2", "—")
                badge_color = "#A8A8A8" if ct1 in ("unclassified", "no cloud") else ct_color(ct1)
                st.markdown(
                    f'<span style="background:{badge_color};color:white;'
                    f'padding:2px 8px;border-radius:4px;font-size:0.85em">☁️ {ct1}</span>'
                    f"&nbsp; subtypes: `{st1}` / `{st2}`",
                    unsafe_allow_html=True,
                )
                url = str(row["image_url"])
                st.markdown(f"[Go to photo online ↗]({url})")

            with c_qr:
                st.markdown("**QR code**")
                st.caption("Scan to open photo")
                qr_img = make_qr(str(row["image_url"]))
                st.image(qr_img, width=150)


# ══════════════════════════════════════════════════════════
# TAB 3 — Feel (Weather by location & cloud type)
# ══════════════════════════════════════════════════════════
with tab3:
    st.header("Feel — Weather by Location & Cloud Type")
    st.caption("Sidebar filters do not apply here. Use the controls below.")

    # ── Top row: location inputs + map ──────────────────────
    col_loc, col_map = st.columns([1, 1])

    with col_loc:
        st.subheader("Location")
        loc_mode = st.radio("Find location by", ["Place name", "Coordinates"], horizontal=True, key="feel_mode")

        if loc_mode == "Place name":
            feel_name = st.text_input("Place name", "Brussels, Belgium", key="feel_name")
            if feel_name:
                geo = geocode_name(feel_name)
                if geo:
                    feel_lat, feel_lon, feel_display = geo
                    st.caption(f"📍 {feel_display}")
                    st.caption(f"Coordinates: {feel_lat:.4f}, {feel_lon:.4f}")
                else:
                    st.warning("Location not found. Try a different name.")
                    feel_lat, feel_lon = 50.85, 4.35
            else:
                feel_lat, feel_lon = 50.85, 4.35
        else:
            feel_lat = st.number_input("Latitude",  value=50.85, format="%.4f", key="feel_lat")
            feel_lon = st.number_input("Longitude", value=4.35,  format="%.4f", key="feel_lon")
            place_name = reverse_geocode(feel_lat, feel_lon)
            if place_name:
                st.caption(f"📍 {place_name}")

        feel_radius = st.slider("Radius (km)", 10, 500, 100, step=10, key="feel_radius")

        st.markdown("---")
        st.subheader("Cloud filter")
        feel_filter_mode = st.radio("Filter by", ["Main cloud type", "Subtype"], horizontal=True, key="feel_fmode")
        if feel_filter_mode == "Main cloud type":
            # Exclude "unclassified" from the selectable options (rows are kept in data)
            _ct_opts = sorted([
                t for t in df_all["cloud_type1"].dropna().unique()
                if t != "unclassified"
            ])
            feel_cloud_all = st.checkbox("All main types", value=True, key="feel_ct_all")
            if feel_cloud_all:
                feel_cloud = "All"
                feel_subtype = None
                st.caption("Showing all main cloud types. To compare up to 3 types side by side, uncheck 'All main types' and select your types.")
            else:
                feel_cloud_sel = st.multiselect(
                    "Select up to 3 cloud types", _ct_opts, max_selections=3, key="feel_ct"
                )
                feel_cloud = feel_cloud_sel if feel_cloud_sel else "All"
                feel_subtype = None
        else:
            _st_opts = sorted(df_all["subtype1"].dropna().unique().tolist())
            feel_st_all = st.checkbox("All subtypes", value=True, key="feel_st_all")
            if feel_st_all:
                feel_subtype = "All"
                feel_cloud = None
                st.caption("Showing all subtypes. To compare up to 3 subtypes side by side, uncheck 'All subtypes' and select your subtypes.")
            else:
                feel_st_sel = st.multiselect(
                    "Select up to 3 subtypes", _st_opts, max_selections=3, key="feel_st"
                )
                feel_subtype = feel_st_sel if feel_st_sel else "All"
                feel_cloud = None

        st.markdown("---")
        st.subheader("Chart & parameters")
        feel_chart = st.radio("Chart type", ["Boxplot", "Violin"], horizontal=True, key="feel_chart")
        feel_p1 = st.selectbox("Parameter 1", list(FEEL_PARAMS.keys()), index=0, key="feel_p1")
        feel_p2 = st.selectbox("Parameter 2", list(FEEL_PARAMS.keys()), index=1, key="feel_p2")
        feel_p3 = st.selectbox("Parameter 3", list(FEEL_PARAMS.keys()), index=4, key="feel_p3")

    with col_map:
        st.subheader("Map")
        _m = folium.Map(location=[feel_lat, feel_lon], zoom_start=7, tiles="CartoDB positron")
        Marker(
            location=[feel_lat, feel_lon],
            tooltip="Selected location",
        ).add_to(_m)
        Circle(
            location=[feel_lat, feel_lon],
            radius=feel_radius * 1000,
            color="#5B7FA6",
            fill=True,
            fill_opacity=0.15,
            weight=2,
        ).add_to(_m)
        st_folium(_m, height=420, use_container_width=True)

    # ── Data source: quality_df by default ──────────────────
    st.markdown("---")
    use_full = st.checkbox(
        "Include all rows (lower quality — fallback datetime)",
        value=False,
        key="feel_use_full",
        help="By default only rows with a reliable capture time (EXIF/XMP/FILENAME) are used, "
             "plus all no-cloud rows. Tick this to include fallback-time rows as well.",
    )
    _feel_base = df_all if use_full else make_quality_df(df_all)

    # ── Filter data ──────────────────────────────────────────
    df_feel = bounding_box_filter(
        _feel_base.dropna(subset=["latitude", "longitude"]),
        feel_lat, feel_lon, feel_radius,
    )
    if feel_cloud and feel_cloud != "All":
        df_feel = df_feel[df_feel["cloud_type1"].isin(feel_cloud)]
    elif feel_cloud == "All":
        df_feel = df_feel[df_feel["cloud_type1"] != "unclassified"]
    if feel_subtype and feel_subtype != "All":
        df_feel = df_feel[df_feel["subtype1"].isin(feel_subtype)]

    # Compute temp−dewpoint diff
    if "temp" in df_feel.columns and "dew_point" in df_feel.columns:
        df_feel = df_feel.copy()
        df_feel["_tdp_diff"] = df_feel["temp"] - df_feel["dew_point"]

    st.metric("Observations in area", f"{len(df_feel):,}")

    # ── Charts ───────────────────────────────────────────────
    if df_feel.empty:
        st.info("No observations found in this area. Try a larger radius.")
    else:
        group_col = "subtype1" if feel_filter_mode == "Subtype" else "cloud_type1"
        group_label = "Subtype" if feel_filter_mode == "Subtype" else "Cloud type"

        for param_label in [feel_p1, feel_p2, feel_p3]:
            col_name = FEEL_PARAMS[param_label]
            if col_name not in df_feel.columns:
                st.caption(f"`{col_name}` not available in this dataset.")
                continue
            data = df_feel.dropna(subset=[col_name, group_col])
            if data.empty:
                st.caption(f"No data for {param_label} in this area.")
                continue

            if feel_chart == "Boxplot":
                fig = px.box(
                    data, x=group_col, y=col_name,
                    color=group_col,
                    color_discrete_map=CLOUD_TYPE_COLORS if group_col == "cloud_type1" else {},
                    labels={group_col: group_label, col_name: param_label},
                    title=param_label,
                    points="outliers",
                )
            else:
                fig = px.violin(
                    data, x=group_col, y=col_name,
                    color=group_col,
                    color_discrete_map=CLOUD_TYPE_COLORS if group_col == "cloud_type1" else {},
                    labels={group_col: group_label, col_name: param_label},
                    title=param_label,
                    box=True,
                    points=False,
                )
            fig.update_layout(showlegend=False, height=380, xaxis_title="")
            st.plotly_chart(fig, width="stretch")


# ══════════════════════════════════════════════════════════
# TAB 4 — Cloud Info
# ══════════════════════════════════════════════════════════
CLOUD_INFO = {
    "Cumulus": {
        "emoji": "⛅",
        "altitude": "Low–mid (600–2,000 m)",
        "description": "Puffy, cauliflower-shaped clouds with flat bases and rounded tops. They form by convection on sunny days when warm air rises. Usually indicate fair weather, but can grow into cumulonimbus.",
        "weather_signal": "High temperature, moderate humidity, low pressure gradient. CAPE > 0 indicates potential for growth.",
    },
    "Cumulonimbus": {
        "emoji": "⛈️",
        "altitude": "Low to very high (up to 15 km)",
        "description": "Towering storm clouds that can reach the tropopause. Associated with heavy rain, lightning, hail and strong winds. The anvil-shaped top is a classic sign.",
        "weather_signal": "High CAPE, strong wind shear, rapidly falling pressure, high humidity. Cloud cover often total.",
    },
    "Stratus": {
        "emoji": "🌫️",
        "altitude": "Very low (0–600 m)",
        "description": "Uniform gray sheet covering the sky like a blanket. Often brings drizzle. Essentially fog that is not touching the ground.",
        "weather_signal": "High humidity, low temperature spread (temp ≈ dew point), stable atmosphere, low wind.",
    },
    "Stratocumulus": {
        "emoji": "🌥️",
        "altitude": "Low (600–2,000 m)",
        "description": "The most common cloud type globally. Low, lumpy gray-white patches or rolls. Usually no significant precipitation.",
        "weather_signal": "Moderate humidity, stable air, low wind shear. Very common in coastal and marine environments.",
    },
    "Altostratus": {
        "emoji": "☁️",
        "altitude": "Mid (2,000–7,000 m)",
        "description": "Gray or blue-gray sheet covering the whole sky. The sun appears as if seen through frosted glass. Often precedes rain or snow.",
        "weather_signal": "Approaching warm front, falling pressure, increasing humidity. Often followed by nimbostratus.",
    },
    "Altocumulus": {
        "emoji": "🌤️",
        "altitude": "Mid (2,000–7,000 m)",
        "description": "Rows or patches of rounded white or gray puffs, smaller than stratocumulus. A 'mackerel sky'. Can signal approaching thunderstorms if castellanus variety appears.",
        "weather_signal": "Mid-level instability, moderate humidity. Castellanus form = convective instability aloft.",
    },
    "Cirrus": {
        "emoji": "🌬️",
        "altitude": "High (>6,000 m)",
        "description": "Thin, wispy ice-crystal clouds in streaks or curls. Often called 'mare's tails'. The first sign of an approaching weather front.",
        "weather_signal": "High-altitude moisture, jet stream activity. Low surface impact but signals weather change in 24–48h.",
    },
    "Cirrostratus": {
        "emoji": "🔆",
        "altitude": "High (>6,000 m)",
        "description": "Thin, transparent ice-crystal sheet covering the sky. Creates halos around the sun or moon. Often precedes frontal rain by 12–24 hours.",
        "weather_signal": "Advancing warm front, slowly falling pressure. Halo effect is a classic rain-forecasting sign.",
    },
    "Cirrocumulus": {
        "emoji": "🌊",
        "altitude": "High (>6,000 m)",
        "description": "Small white puffs in rippled rows — the 'mackerel sky' at high altitude. Rare and short-lived. Made of supercooled water droplets.",
        "weather_signal": "High-altitude instability, tropical or frontal systems nearby.",
    },
    "Nimbostratus": {
        "emoji": "🌧️",
        "altitude": "Low–mid (0–4,000 m)",
        "description": "Thick, dark gray layer that blocks out the sun completely. The classic 'rainy day' cloud — produces continuous, steady rain or snow.",
        "weather_signal": "High cloud cover, high humidity, falling pressure, low visibility. Rain_1h typically > 0.",
    },
}

WEATHER_INFO = {
    "Temperature": "Air temperature at 2m height (°C). Cumulus and cumulonimbus typically form on warm days (high surface temp drives convection). Stratus and fog form near the dew point temperature.",
    "Dew point": "The temperature at which air becomes saturated. When temp ≈ dew point, fog or stratus forms. A large spread (temp − dew point > 10°C) indicates dry air, favoring convective clouds.",
    "Humidity": "Relative humidity (%). 100% = saturated. High humidity (>85%) is needed for most cloud formation. Low humidity (<40%) suppresses cloud formation.",
    "Pressure": "Sea-level atmospheric pressure (hPa). Falling pressure signals approaching low-pressure systems and cloud/rain. Normal ≈ 1013 hPa. Below 1000 = active weather likely.",
    "Cloud cover": "Total cloud cover (%). The fraction of sky covered by clouds. Low-level, mid-level and high-level fractions are also available and help distinguish cloud families.",
    "Wind speed / gusts": "Wind speed at 10m (km/h). Strong wind shear (wind changing speed or direction with height) is needed for cumulonimbus development and can shape cloud appearance.",
    "Rain / Snow": "Precipitation in the past hour (mm). Nimbostratus and cumulonimbus are the main rain producers. Light rain/drizzle is characteristic of stratus.",
    "Weather code": "WMO weather condition code (0–99). 0 = clear sky, 1–3 = partly cloudy, 45/48 = fog, 51–67 = drizzle/rain, 71–77 = snow, 80–82 = showers, 95–99 = thunderstorm.",
}

with tab4:
    st.header("Cloud Types & Weather Parameters")

    col_left, col_right = st.columns([1, 1])

    with col_left:
        st.subheader("The 10 cloud genera")
        st.caption("Click on a cloud type to expand its description.")

        for name, info in CLOUD_INFO.items():
            color = CLOUD_TYPE_COLORS.get(name.lower(), "#888")
            with st.expander(f"{info['emoji']}  {name}  —  {info['altitude']}"):
                st.markdown(
                    f'<div style="border-left: 4px solid {color}; padding-left: 12px;">'
                    f"<p>{info['description']}</p>"
                    f"<p><b>Weather signal:</b> {info['weather_signal']}</p>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

    with col_right:
        st.subheader("Weather parameters")
        st.caption("Click on a parameter to expand its description.")

        for param, desc in WEATHER_INFO.items():
            with st.expander(param):
                st.markdown(desc)