"""
Analysis functions for the VeryCloudy dataset.

All functions accept a pandas DataFrame and return a matplotlib Figure
(or None for interactive widget functions). No display logic lives here —
that belongs in the notebook.

Typical notebook pattern
------------------------
    standard_style()
    df       = pd.read_csv(FILEPATH_DATASET_TO_SHARE, low_memory=False)
    quality_df = make_quality_df(df)          # reliable datetimes only

    # Cloud-type charts: use df (all rows)
    fig = cloud_type_bar(df);  plt.show()

    # Weather charts: use quality_df by default
    weather_histograms_interactive(quality_df)

Data filters applied inside functions
--------------------------------------
- _filter_valid_year   : drops the 1980 outlier row (all chart functions)
- _filter_good_weather : drops rows where is_cloudy=True AND clouds=0
                         (weather and scatter functions)
- make_quality_df      : keeps only rows with EXIF / XMP / FILENAME datetime
                         source; call this once in the notebook, then pass
                         quality_df to weather-related functions
"""

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd

from verycloudy.styling import standard_style, CLOUD_TYPE_COLORS, NO_CLOUD, PALETTE

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CLOUD_ORDER = [
    "cumulus", "cumulonimbus", "stratocumulus", "stratus",
    "nimbostratus", "altostratus", "altocumulus",
    "cirrus", "cirrostratus", "cirrocumulus",
    "no cloud", "unclassified",
]

CLOUD_ALTITUDE = {
    "high": ["cirrus", "cirrostratus", "cirrocumulus"],
    "mid":  ["altostratus", "altocumulus", "nimbostratus"],
    "low":  ["cumulus", "cumulonimbus", "stratocumulus", "stratus"],
}

ALTITUDE_LABELS = {
    "high": "High clouds  (cirrus family)",
    "mid":  "Mid clouds  (alto family)",
    "low":  "Low clouds  (cumulus / stratus family)",
}

ALTITUDE_COLORS = {
    "high": PALETTE[6],   # LAVENDER
    "mid":  PALETTE[4],   # OLIVE
    "low":  PALETTE[3],   # SLATE_BLUE
}

# Weather variables used in histogram and boxplot functions.
# Excluded: dew_point (replaced by temp-dew_point spread), rain_1h, snow_1h
#           (often empty), cloud-cover columns, wind_gust, wind_deg,
#           visibility and uvi (0 non-null in current dataset).
# "temp_dew_spread" is a derived column computed inside each function.
WEATHER_VARS = [
    ("temp",            "Temperature (°C)"),
    ("humidity",        "Humidity (%)"),
    ("pressure",        "Pressure (hPa)"),
    ("temp_dew_spread", "Temp − Dew Point (°C)"),
    ("wind_speed",      "Wind Speed (km/h)"),
]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _cloud_label(df: pd.DataFrame) -> pd.Series:
    """
    Return the primary cloud label per row.

    1. cloud_type1 filled        → cloud_type1 (lower-stripped)
    2. is_cloudy == False        → 'no cloud'
    3. cloud_type1 empty + subtype1 filled → NaN  (rare phenomena, excluded)
    4. both empty, is_cloudy True → 'unclassified'
    """
    t1 = df["cloud_type1"].replace("", pd.NA).str.lower().str.strip()
    s1 = (df["subtype1"].replace("", pd.NA)
          if "subtype1" in df.columns
          else pd.Series(pd.NA, index=df.index))
    is_cloudy = (df["is_cloudy"]
                 if "is_cloudy" in df.columns
                 else pd.Series(True, index=df.index))

    labels = t1.copy()
    labels[is_cloudy.eq(False)] = "no cloud"
    mask_unclassified = t1.isna() & s1.isna() & ~is_cloudy.eq(False)
    labels[mask_unclassified] = "unclassified"
    return labels


def _color_list(labels: list[str]) -> list[str]:
    return [CLOUD_TYPE_COLORS.get(l, NO_CLOUD) for l in labels]


def _filter_valid_year(df: pd.DataFrame) -> pd.DataFrame:
    """Drop the single 1980 outlier row."""
    years = pd.to_datetime(df["date_taken"], errors="coerce").dt.year
    return df[years.ne(1980) | years.isna()]


def _filter_good_weather(df: pd.DataFrame) -> pd.DataFrame:
    """Drop rows where is_cloudy=True but total cloud cover=0 (weather API anomaly)."""
    if "is_cloudy" not in df.columns or "clouds" not in df.columns:
        return df
    bad = df["is_cloudy"].eq(True) & df["clouds"].eq(0)
    return df[~bad]


def _owm_weather_group(code: float) -> str:
    """Map an OpenWeatherMap numeric code to a broad readable category."""
    if pd.isna(code):
        return "Unknown"
    c = int(code)
    if c == 800:        return "Clear"
    if c == 801:        return "Few clouds"
    if 802 <= c <= 804: return "Overcast / Broken"
    if 200 <= c <= 299: return "Thunderstorm"
    if 300 <= c <= 399: return "Drizzle"
    if 500 <= c <= 599: return "Rain"
    if 600 <= c <= 699: return "Snow"
    if 700 <= c <= 799: return "Mist / Fog"
    return "Other"


# ---------------------------------------------------------------------------
# Public helper — call once in the notebook
# ---------------------------------------------------------------------------

def make_quality_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Return the subset of rows with reliable data.

    Includes:
    - Rows where ``datetime_source`` contains 'EXIF', 'XMP', or 'FILENAME':
      the capture time is known, so the weather API was queried for the
      correct hour.
    - All rows where ``is_cloudy == False``: these are the negative class
      (straight from Open Meteo, no photo involved) and are always quality
      data regardless of datetime_source.

    Rows with fallback time 11:00 and is_cloudy=True are excluded because
    the weather at the actual capture time is unknown and adds noise.

    Usage in notebook::

        quality_df = make_quality_df(df)
        weather_histograms_interactive(quality_df)   # default
        weather_histograms_interactive(df)           # if you want all rows
    """
    good_datetime = pd.Series(False, index=df.index)
    if "datetime_source" in df.columns:
        good_datetime = df["datetime_source"].notna() & df["datetime_source"].str.upper().str.contains(
            "EXIF|XMP|FILENAME", na=False
        )

    no_cloud_rows = pd.Series(False, index=df.index)
    if "is_cloudy" in df.columns:
        no_cloud_rows = df["is_cloudy"].eq(False)

    return df[good_datetime | no_cloud_rows].copy()


# ============================================================
# A. Dataset overview
# ============================================================

def data_quality_report(df: pd.DataFrame) -> pd.DataFrame:
    """
    Print a data-quality summary and return it as a DataFrame.

    Checks:
    - Missing weather information and overlap with missing location
    - Rows where is_cloudy=True but cloud cover=0 (weather API anomaly)
      and how many of those used fallback time 11:00
    - The single 1980 outlier row
    - Quality rows (EXIF / XMP / FILENAME datetime source)
    """
    n = len(df)

    no_weather  = df["temp"].isna() if "temp" in df.columns else pd.Series(False, index=df.index)
    no_lat      = df["latitude"].isna() if "latitude" in df.columns else pd.Series(True, index=df.index)
    no_lon      = df["longitude"].isna() if "longitude" in df.columns else pd.Series(True, index=df.index)
    no_location = no_lat | no_lon

    n_no_weather          = int(no_weather.sum())
    n_no_weather_no_loc   = int((no_weather & no_location).sum())
    n_no_weather_with_loc = n_no_weather - n_no_weather_no_loc

    if "is_cloudy" in df.columns and "clouds" in df.columns:
        bad_cover  = df["is_cloudy"].eq(True) & df["clouds"].eq(0)
        n_bad_cover = int(bad_cover.sum())
        n_bad_fallback = (int((bad_cover & df["fallback_dt_used"].eq(True)).sum())
                          if "fallback_dt_used" in df.columns else "n/a")
    else:
        n_bad_cover = n_bad_fallback = "n/a"

    years  = pd.to_datetime(df["date_taken"], errors="coerce").dt.year
    n_1980 = int(years.eq(1980).sum())

    n_quality = len(make_quality_df(df))

    rows = [
        {"check": "Total rows",                                 "count": n,                    "note": ""},
        {"check": "Rows without weather info",                  "count": n_no_weather,          "note": f"{100*n_no_weather/n:.1f}% of all rows"},
        {"check": "  → also no location",                       "count": n_no_weather_no_loc,   "note": "weather lookup impossible"},
        {"check": "  → have location but no weather",           "count": n_no_weather_with_loc, "note": "2 rows; likely too old for archive"},
        {"check": "is_cloudy=True AND cloud cover=0",           "count": n_bad_cover,           "note": "weather API anomaly; excluded from weather charts"},
        {"check": "  → used fallback time 11:00",               "count": n_bad_fallback,        "note": "time unknown → wrong hour sent to API"},
        {"check": "Rows with date year = 1980",                 "count": n_1980,                "note": "outlier; excluded from all charts"},
        {"check": "Quality rows (EXIF / XMP / FILENAME source)","count": n_quality,             "note": f"{100*n_quality/n:.1f}% — use these for weather analysis"},
    ]

    result = pd.DataFrame(rows)
    print(result.to_string(index=False))
    return result


def summary_table(df: pd.DataFrame) -> pd.DataFrame:
    """
    Return a summary DataFrame with four columns (metric / count / missing / pct).
    Shows dataset size, date range, geographic diversity, completeness, and cloud
    label distribution.
    """
    n = len(df)

    def _fill(col):
        return int(df[col].notna().sum()) if col in df.columns else 0

    def _pct(count):
        return round(100 * count / n, 1) if n > 0 else 0.0

    def _completeness_row(label, col):
        filled = _fill(col)
        return {"metric": label, "count": filled, "missing": n - filled, "pct": _pct(filled)}

    date_series  = pd.to_datetime(df["date_taken"], errors="coerce")
    unique_countries = df["country"].nunique() if "country" in df.columns else "?"
    if "latitude" in df.columns and "longitude" in df.columns:
        unique_locs = int(df[["latitude", "longitude"]].dropna().drop_duplicates().shape[0])
    else:
        unique_locs = "?"

    t1 = df["cloud_type1"].replace("", pd.NA) if "cloud_type1" in df.columns else pd.Series(pd.NA, index=df.index)
    s1 = df["subtype1"].replace("", pd.NA)   if "subtype1"    in df.columns else pd.Series(pd.NA, index=df.index)
    is_cloudy = df["is_cloudy"] if "is_cloudy" in df.columns else pd.Series(True, index=df.index)

    rows = [
        {"metric": "total rows",        "count": n,                     "missing": "", "pct": ""},
        {"metric": "date range start",  "count": str(date_series.min().date()) if date_series.notna().any() else "?", "missing": "", "pct": ""},
        {"metric": "date range end",    "count": str(date_series.max().date()) if date_series.notna().any() else "?", "missing": "", "pct": ""},
        {"metric": "unique countries",  "count": unique_countries,       "missing": "", "pct": ""},
        {"metric": "unique locations",  "count": unique_locs,            "missing": "", "pct": ""},
        _completeness_row("date taken",  "date_taken"),
        _completeness_row("time taken",  "time_taken"),
        _completeness_row("temp",        "temp"),
        _completeness_row("latitude",    "latitude"),
        _completeness_row("longitude",   "longitude"),
        {"metric": "— cloud labels —",  "count": "",                     "missing": "", "pct": ""},
        {"metric": "with main type",    "count": int(t1.notna().sum()),  "missing": "", "pct": _pct(int(t1.notna().sum()))},
        {"metric": "subtype only",      "count": int((t1.isna() & s1.notna() & ~is_cloudy.eq(False)).sum()), "missing": "", "pct": ""},
        {"metric": "no cloud",          "count": int(is_cloudy.eq(False).sum()), "missing": "", "pct": ""},
        {"metric": "unclassified",      "count": int((t1.isna() & s1.isna() & ~is_cloudy.eq(False)).sum()),  "missing": "", "pct": ""},
    ]
    return pd.DataFrame(rows)


def rows_per_year(df: pd.DataFrame) -> plt.Figure:
    """Bar chart: number of rows per year. Excludes the 1980 outlier."""
    standard_style()
    df_f  = _filter_valid_year(df)
    years = pd.to_datetime(df_f["date_taken"], errors="coerce").dt.year.dropna().astype(int)
    counts = years.value_counts().sort_index()

    fig, ax = plt.subplots(figsize=(18, 6))
    ax.bar(counts.index, counts.values, color=PALETTE[0], width=0.7)
    ax.set_xlabel("Year")
    ax.set_ylabel("Number of rows")
    ax.set_title("Rows per year  (1980 outlier excluded)")
    ax.set_xticks(counts.index)
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    return fig


# ============================================================
# B. Geographic spread
# ============================================================

def top_countries_bar(df: pd.DataFrame, n: int = 20) -> plt.Figure:
    """Horizontal bar chart: top N countries, with count labels."""
    standard_style()
    df_f   = _filter_valid_year(df)
    counts = df_f["country"].value_counts().head(n)

    fig, ax = plt.subplots(figsize=(9, max(4, n * 0.35)))
    bars = ax.barh(counts.index[::-1], counts.values[::-1], color=PALETTE[0])
    ax.set_xlabel("Number of rows")
    ax.set_title(f"Top {n} countries")

    x_max = counts.values.max()
    for bar, val in zip(bars, counts.values[::-1]):
        ax.text(
            bar.get_width() + x_max * 0.005,
            bar.get_y() + bar.get_height() / 2,
            f"{val:,}",
            va="center", fontsize=11,
        )
    ax.set_xlim(right=x_max * 1.12)
    fig.tight_layout()
    return fig


# ============================================================
# C. Cloud types
# ============================================================

def cloud_type_bar(df: pd.DataFrame) -> plt.Figure:
    """Bar chart: frequency of primary cloud type, sorted descending, counts on top."""
    standard_style()
    df_f   = _filter_valid_year(df)
    labels = _cloud_label(df_f)
    counts = labels.value_counts().sort_values(ascending=False)

    colors = _color_list(counts.index.tolist())
    fig, ax = plt.subplots(figsize=(11, 5))
    bars = ax.bar(counts.index, counts.values, color=colors, width=0.7)
    ax.bar_label(bars, padding=3, fontsize=10)
    ax.set_xlabel("Cloud type")
    ax.set_ylabel("Count")
    ax.set_title("Frequency of primary cloud type")
    ax.tick_params(axis="x", rotation=40)
    ax.set_ylim(top=counts.values.max() * 1.12)
    fig.tight_layout()
    return fig


def subtype_bar(df: pd.DataFrame, n: int = 15) -> plt.Figure:
    """Bar chart: top N subtypes (subtype1 + subtype2 combined), counts on top."""
    standard_style()
    df_f = _filter_valid_year(df)
    s1   = df_f["subtype1"].dropna() if "subtype1" in df_f.columns else pd.Series(dtype=str)
    s2   = df_f["subtype2"].dropna() if "subtype2" in df_f.columns else pd.Series(dtype=str)
    counts = pd.concat([s1, s2]).str.lower().str.strip().value_counts().head(n)

    fig, ax = plt.subplots(figsize=(10, 4))
    bars = ax.bar(counts.index, counts.values, color=PALETTE[0], width=0.7)
    ax.bar_label(bars, padding=3, fontsize=10)
    ax.set_xlabel("Subtype")
    ax.set_ylabel("Count")
    ax.set_title(f"Top {n} cloud subtypes")
    ax.tick_params(axis="x", rotation=40)
    ax.set_ylim(top=counts.values.max() * 1.12)
    fig.tight_layout()
    return fig


def cooccurrence_heatmap(df: pd.DataFrame) -> plt.Figure:
    """
    Heatmap: how often cloud_type1 co-occurs with cloud_type2.
    Grey diagonal = same type on both axes.
    """
    standard_style()
    df_f = _filter_valid_year(df)
    sub  = df_f[df_f["cloud_type1"].notna() & df_f["cloud_type2"].notna()].copy()
    sub["t1"] = sub["cloud_type1"].str.lower().str.strip()
    sub["t2"] = sub["cloud_type2"].str.lower().str.strip()

    types  = [c for c in CLOUD_ORDER if c not in ("no cloud", "unclassified")]
    matrix = pd.crosstab(sub["t1"], sub["t2"]).reindex(index=types, columns=types, fill_value=0)

    fig, ax = plt.subplots(figsize=(10, 8))
    im = ax.imshow(matrix.values, cmap="YlOrBr", aspect="auto")
    ax.set_xticks(range(len(matrix.columns)))
    ax.set_yticks(range(len(matrix.index)))
    ax.set_xticklabels(matrix.columns, rotation=45, ha="right")
    ax.set_yticklabels(matrix.index)
    ax.set_title("Co-occurrence: cloud_type1 vs cloud_type2\n(grey = same type on both axes)")
    ax.set_xlabel("cloud_type2")
    ax.set_ylabel("cloud_type1")
    plt.colorbar(im, ax=ax, shrink=0.7, label="count")

    for i in range(len(matrix.index)):
        for j in range(len(matrix.columns)):
            v = matrix.values[i, j]
            if v > 0:
                ax.text(j, i, str(v), ha="center", va="center", fontsize=9)

    cols_list = matrix.columns.tolist()
    for i, t in enumerate(matrix.index):
        if t in cols_list:
            j = cols_list.index(t)
            ax.add_patch(mpatches.Rectangle(
                (j - 0.5, i - 0.5), 1, 1, color="#AAAAAA", zorder=2, alpha=0.85,
            ))

    fig.tight_layout()
    return fig


def cooccurrence_cloudtype_subtype(df: pd.DataFrame, n_subtypes: int = 15) -> plt.Figure:
    """
    Heatmap: how often each cloud_type1 co-occurs with each subtype1.
    Top n_subtypes subtypes on the x-axis.
    """
    standard_style()
    df_f = _filter_valid_year(df)
    sub  = df_f[df_f["cloud_type1"].notna() & df_f["subtype1"].notna()].copy()
    sub["t1"] = sub["cloud_type1"].str.lower().str.strip()
    sub["s1"] = sub["subtype1"].str.lower().str.strip()

    top_subs = sub["s1"].value_counts().head(n_subtypes).index.tolist()
    sub      = sub[sub["s1"].isin(top_subs)]

    types  = [c for c in CLOUD_ORDER if c not in ("no cloud", "unclassified") and c in sub["t1"].unique()]
    matrix = pd.crosstab(sub["t1"], sub["s1"]).reindex(index=types, columns=top_subs, fill_value=0)

    fig, ax = plt.subplots(figsize=(14, 7))
    im = ax.imshow(matrix.values, cmap="YlOrBr", aspect="auto")
    ax.set_xticks(range(len(matrix.columns)))
    ax.set_yticks(range(len(matrix.index)))
    ax.set_xticklabels(matrix.columns, rotation=45, ha="right")
    ax.set_yticklabels(matrix.index)
    ax.set_title(f"Co-occurrence: cloud_type1 vs subtype1  (top {n_subtypes} subtypes)")
    ax.set_xlabel("Subtype")
    ax.set_ylabel("Cloud type")
    plt.colorbar(im, ax=ax, shrink=0.7, label="count")

    for i in range(len(matrix.index)):
        for j in range(len(matrix.columns)):
            v = matrix.values[i, j]
            if v > 0:
                ax.text(j, i, str(v), ha="center", va="center", fontsize=8)

    fig.tight_layout()
    return fig


# ============================================================
# D. Cloud observations by time
# ============================================================

def cloud_by_hour(df: pd.DataFrame) -> plt.Figure:
    """
    Static line chart: total cloud observations by hour of day.

    Rows with fallback time 11:00 are excluded (time is unknown for those rows).
    Pass quality_df for the cleanest result.
    """
    standard_style()
    df_f = _filter_valid_year(df)
    if "fallback_dt_used" in df_f.columns:
        df_f = df_f[df_f["fallback_dt_used"].ne(True)]

    df_f = df_f.copy()
    df_f["hour"] = pd.to_datetime(df_f["time_taken"], format="%H:%M:%S", errors="coerce").dt.hour
    counts = df_f.groupby("hour").size().reindex(range(24), fill_value=0)

    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(range(24), counts.values,
            color=PALETTE[0], linewidth=2.5, marker="o", markersize=6)
    ax.fill_between(range(24), counts.values, alpha=0.15, color=PALETTE[0])
    ax.set_xlabel("Hour of day")
    ax.set_ylabel("Number of observations")
    ax.set_title("Cloud observations by hour of day\n(rows with fallback time 11:00 excluded)")
    ax.set_xticks(range(24))
    ax.set_xlim(-0.5, 23.5)
    ax.set_ylim(bottom=0)
    fig.tight_layout()
    return fig


# ============================================================
# E. Weather distributions  — pass quality_df for reliable results
# ============================================================

def weather_histograms_interactive(df: pd.DataFrame) -> None:
    """
    Interactive matplotlib histograms using ipywidgets.

    A dropdown selects the weather variable; two side-by-side panels show
    the distribution for Cloudy vs No cloud rows separately.

    Pass quality_df (datetime_source EXIF/XMP/FILENAME) for reliable results —
    fallback rows have an unknown capture time and may have noisy weather values.

    Variables: temp, humidity, pressure, temp−dew_point spread, wind_speed.
    Excluded: dew_point (replaced by spread), rain_1h, snow_1h (often empty),
    cloud-cover columns, wind_gust, wind_deg, visibility (empty), uvi (empty).
    """
    try:
        import ipywidgets as widgets
    except ImportError:
        raise ImportError("ipywidgets is required for interactive plots. "
                          "Install it with: pip install ipywidgets")

    df_f = _filter_valid_year(_filter_good_weather(df)).copy()
    if "temp" in df_f.columns and "dew_point" in df_f.columns:
        df_f["temp_dew_spread"] = df_f["temp"] - df_f["dew_point"]

    valid_vars = [
        (col, lbl) for col, lbl in WEATHER_VARS
        if col in df_f.columns and df_f[col].notna().any()
    ]

    cloudy   = df_f[df_f["is_cloudy"].eq(True)]
    no_cloud = df_f[df_f["is_cloudy"].eq(False)]

    var_map = {col: lbl for col, lbl in valid_vars}

    def _draw(col):
        lbl = var_map.get(col, col)
        standard_style()
        fig, axes = plt.subplots(1, 2, figsize=(12, 5))

        for ax, subset, name, color in [
            (axes[0], cloudy,   "Cloudy",   PALETTE[0]),
            (axes[1], no_cloud, "No cloud", NO_CLOUD),
        ]:
            data = subset[col].dropna()
            ax.hist(data, bins=40, color=color, alpha=0.85)
            ax.set_title(f"{name}  (n={len(data):,})")
            ax.set_xlabel(lbl)
            ax.set_ylabel("Count")

        fig.suptitle(f"Distribution of {lbl}", fontsize=14, fontweight="bold")
        fig.tight_layout()
        plt.show()

    widgets.interact(
        _draw,
        col=widgets.Dropdown(
            options=[(lbl, col) for col, lbl in valid_vars],
            description="Variable:",
            style={"description_width": "initial"},
        ),
    )


def boxplots_interactive(df: pd.DataFrame) -> None:
    """
    Interactive matplotlib box plots using ipywidgets.

    A dropdown selects the weather variable; two side-by-side panels show
    the distribution for Cloudy vs No cloud rows separately.

    Pass quality_df for reliable results.
    """
    try:
        import ipywidgets as widgets
    except ImportError:
        raise ImportError("ipywidgets is required for interactive plots. "
                          "Install it with: pip install ipywidgets")

    df_f = _filter_valid_year(_filter_good_weather(df)).copy()
    if "temp" in df_f.columns and "dew_point" in df_f.columns:
        df_f["temp_dew_spread"] = df_f["temp"] - df_f["dew_point"]

    valid_vars = [
        (col, lbl) for col, lbl in WEATHER_VARS
        if col in df_f.columns and df_f[col].notna().any()
    ]

    cloudy   = df_f[df_f["is_cloudy"].eq(True)]
    no_cloud = df_f[df_f["is_cloudy"].eq(False)]

    var_map = {col: lbl for col, lbl in valid_vars}

    def _draw(col):
        lbl = var_map.get(col, col)
        standard_style()
        fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)

        for ax, subset, name, color in [
            (axes[0], cloudy,   "Cloudy",   PALETTE[0]),
            (axes[1], no_cloud, "No cloud", NO_CLOUD),
        ]:
            data = subset[col].dropna()
            bp = ax.boxplot(
                [data], patch_artist=True, widths=0.45,
                medianprops=dict(color="white", linewidth=2),
                flierprops=dict(marker=".", markersize=3, alpha=0.3),
            )
            bp["boxes"][0].set_facecolor(color)
            bp["boxes"][0].set_alpha(0.85)
            ax.set_title(f"{name}  (n={len(data):,})")
            ax.set_ylabel(lbl)
            ax.set_xticks([])

        fig.suptitle(f"{lbl}  —  Cloudy vs No cloud", fontsize=14, fontweight="bold")
        fig.tight_layout()
        plt.show()

    widgets.interact(
        _draw,
        col=widgets.Dropdown(
            options=[(lbl, col) for col, lbl in valid_vars],
            description="Variable:",
            style={"description_width": "initial"},
        ),
    )


def dew_spread_by_altitude(df: pd.DataFrame) -> plt.Figure:
    """
    Box plot: dew point spread (temp − dew_point) grouped by cloud altitude level.
    High / mid / low cloud groups shown side by side; individual cloud types as
    separate boxes within each group.

    Pass quality_df for reliable results.
    """
    standard_style()
    df_f = _filter_valid_year(_filter_good_weather(df))
    sub  = df_f[df_f["temp"].notna() & df_f["dew_point"].notna()].copy()
    sub["spread"] = sub["temp"] - sub["dew_point"]
    sub["label"]  = _cloud_label(sub)
    sub = sub[sub["label"].notna() & ~sub["label"].isin(["no cloud", "unclassified"])]

    all_data, positions, pos_labels, pos_colors = [], [], [], []
    pos_current = 1
    group_mid_positions = {}
    separator_positions = []

    for alt_key in ["high", "mid", "low"]:
        types_in_group = [t for t in CLOUD_ALTITUDE[alt_key] if t in sub["label"].unique()]
        if not types_in_group:
            continue
        group_pos_list = []
        for ct in types_in_group:
            data = sub.loc[sub["label"] == ct, "spread"].values
            all_data.append(data)
            positions.append(pos_current)
            pos_labels.append(ct)
            pos_colors.append(ALTITUDE_COLORS[alt_key])
            group_pos_list.append(pos_current)
            pos_current += 1
        group_mid_positions[alt_key] = (group_pos_list[0] + group_pos_list[-1]) / 2
        separator_positions.append(pos_current - 0.25)
        pos_current += 1.5

    fig, ax = plt.subplots(figsize=(13, 6))
    bp = ax.boxplot(
        all_data, positions=positions, patch_artist=True, widths=0.65,
        medianprops=dict(color="white", linewidth=2),
        flierprops=dict(marker=".", markersize=3, alpha=0.4),
    )
    for patch, color in zip(bp["boxes"], pos_colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.85)

    ax.set_xticks(positions)
    ax.set_xticklabels(pos_labels, rotation=40, ha="right")
    ax.axhline(0, color="gray", linestyle="--", linewidth=1, zorder=0)
    ax.set_ylabel("Temp − Dew point  (°C)")
    ax.set_title("Dew point spread by cloud altitude group\n"
                 "(small spread = air near saturation = more cloud formation)")

    for sep_x in separator_positions[:-1]:
        ax.axvline(sep_x, color="#DDDDDD", linewidth=1.2, zorder=0)

    patches = [
        mpatches.Patch(facecolor=ALTITUDE_COLORS[k], alpha=0.85, label=ALTITUDE_LABELS[k])
        for k in ["high", "mid", "low"] if k in group_mid_positions
    ]
    ax.legend(handles=patches, loc="upper right", frameon=False)
    fig.tight_layout()
    return fig


# ============================================================
# F. Cloud type vs weather
# ============================================================

def scatter_temp_dew_cloudy(df: pd.DataFrame) -> plt.Figure:
    """
    Scatter: dew point (x) vs temperature (y), two colours: Cloudy vs No cloud.

    The dashed diagonal (T = Td) is the saturation line: air is 100 % saturated
    when temperature equals dew point.  Cloudy observations cluster near this line;
    clear-sky observations show a larger gap.  This directly illustrates the
    fundamental cloud-formation mechanism and motivates using weather variables
    as ML features.

    Pass quality_df for a cleaner result with fewer points.
    """
    standard_style()
    df_f = _filter_valid_year(_filter_good_weather(df))
    sub  = df_f[df_f["dew_point"].notna() & df_f["temp"].notna()].copy()

    fig, ax = plt.subplots(figsize=(8, 7))
    for is_cl, name, color in [
        (True,  "Cloudy",   "#2171B5"),   # strong blue
        (False, "No cloud", "#F16913"),   # vivid orange
    ]:
        s = sub[sub["is_cloudy"].eq(is_cl)]
        ax.scatter(s["dew_point"], s["temp"],
                   color=color, label=f"{name}  (n={len(s):,})",
                   alpha=0.20, s=10, linewidths=0)

    # Saturation reference line  T = Td
    lo = sub["dew_point"].quantile(0.01)
    hi = sub["dew_point"].quantile(0.99)
    ax.plot([lo, hi], [lo, hi], color="#CC0000", linestyle="--",
            linewidth=1.8, label="Saturation  (T = Td)", zorder=5)

    ax.set_xlabel("Dew Point (°C)")
    ax.set_ylabel("Temperature (°C)")
    ax.set_title("Temperature vs Dew Point\n"
                 "Clouds form when temperature ≈ dew point  (air near saturation)")
    ax.legend(frameon=False)
    fig.tight_layout()
    return fig