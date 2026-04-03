"""
Analysis functions for the VeryCloudy dataset.

All functions accept a pandas DataFrame (the combined cloud + no-cloud dataset)
and return a matplotlib Figure or plotly Figure. No display logic lives here —
that belongs in the notebook.

Usage:
    from verycloudy.analysis import *
    from verycloudy.styling import standard_style
    standard_style()
    fig = cloud_type_bar(df)
    fig.show() / plt.show() / display(fig)

Data filters applied inside functions
--------------------------------------
- _filter_valid_year   : drops the single 1980 outlier row (applied in all chart functions)
- _filter_good_weather : drops rows where is_cloudy=True AND clouds=0 (applied in weather
                         and scatter functions; these rows have impossible/anomalous weather data)
- fallback filter      : cloud_by_hour and scatter-by-type functions additionally drop rows
                         where fallback_dt_used=True (time was set to 11:00 as placeholder)
"""

import calendar

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd
import plotly.graph_objects as go

from verycloudy.styling import standard_style, CLOUD_TYPE_COLORS, NO_CLOUD, PALETTE

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Order used consistently across all charts
CLOUD_ORDER = [
    "cumulus", "cumulonimbus", "stratocumulus", "stratus",
    "nimbostratus", "altostratus", "altocumulus",
    "cirrus", "cirrostratus", "cirrocumulus",
    "no cloud", "unclassified",
]

# Standard WMO altitude classification
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

# Weather variables used across histogram and boxplot functions
# (clouds*, wind_gust, wind_deg, visibility and uvi excluded per design choice;
#  visibility and uvi are also 0 non-null in the current dataset)
WEATHER_VARS = [
    ("temp",       "Temperature (°C)"),
    ("humidity",   "Humidity (%)"),
    ("pressure",   "Pressure (hPa)"),
    ("dew_point",  "Dew Point (°C)"),
    ("wind_speed", "Wind Speed (km/h)"),
    ("rain_1h",    "Rain 1h (mm)"),
    ("snow_1h",    "Snow 1h (mm)"),
]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _cloud_label(df: pd.DataFrame) -> pd.Series:
    """
    Return a Series with the primary cloud label per row.

    Four cases:
    1. cloud_type1 is filled        → cloud_type1 (lowercased/stripped).
    2. is_cloudy == False           → 'no cloud' (genuine clear-sky rows).
    3. cloud_type1 empty, subtype1 filled → NaN (rare phenomena: noctilucent,
       nacreous, etc.; not WMO genera; excluded from type-based charts).
    4. cloud_type1 empty AND subtype1 empty → 'unclassified' (rows whose cloud
       type could not be parsed from available metadata).
    """
    t1 = df["cloud_type1"].replace("", pd.NA).str.lower().str.strip()
    s1 = (df["subtype1"].replace("", pd.NA)
          if "subtype1" in df.columns
          else pd.Series(pd.NA, index=df.index))
    is_cloudy = (df["is_cloudy"]
                 if "is_cloudy" in df.columns
                 else pd.Series(True, index=df.index))

    labels = t1.copy()                                        # case 1
    labels[is_cloudy.eq(False)] = "no cloud"                 # case 2
    mask_unclassified = t1.isna() & s1.isna() & ~is_cloudy.eq(False)
    labels[mask_unclassified] = "unclassified"               # case 4
    # case 3: t1 NaN + s1 filled → labels stays NaN → excluded from charts
    return labels


def _color_list(labels: list[str]) -> list[str]:
    """Map a list of cloud type labels to hex colors."""
    return [CLOUD_TYPE_COLORS.get(l, NO_CLOUD) for l in labels]


def _filter_valid_year(df: pd.DataFrame) -> pd.DataFrame:
    """Drop the single 1980 outlier row (invalid/placeholder date)."""
    years = pd.to_datetime(df["date_taken"], errors="coerce").dt.year
    return df[years.ne(1980) | years.isna()]


def _filter_good_weather(df: pd.DataFrame) -> pd.DataFrame:
    """
    Drop rows where is_cloudy=True but total cloud cover=0.
    These rows have anomalous weather data (cloud photos with 0 % cloud cover
    from the weather API, all of which also used the 11:00 fallback time).
    """
    if "is_cloudy" not in df.columns or "clouds" not in df.columns:
        return df
    bad = df["is_cloudy"].eq(True) & df["clouds"].eq(0)
    return df[~bad]


def _owm_weather_group(code: float) -> str:
    """Map an OpenWeatherMap numeric code to a broad readable category."""
    if pd.isna(code):
        return "Unknown"
    c = int(code)
    if c == 800:
        return "Clear"
    if c == 801:
        return "Few clouds"
    if 802 <= c <= 804:
        return "Overcast / Broken"
    if 200 <= c <= 299:
        return "Thunderstorm"
    if 300 <= c <= 399:
        return "Drizzle"
    if 500 <= c <= 599:
        return "Rain"
    if 600 <= c <= 699:
        return "Snow"
    if 700 <= c <= 799:
        return "Mist / Fog"
    return "Other"


def _drop_fallback(df: pd.DataFrame) -> pd.DataFrame:
    """Drop rows where the time was set to 11:00 as a fallback placeholder."""
    if "fallback_dt_used" not in df.columns:
        return df
    return df[df["fallback_dt_used"].ne(True)]


# ============================================================
# A. Dataset overview
# ============================================================

def data_quality_report(df: pd.DataFrame) -> pd.DataFrame:
    """
    Print a data-quality summary and return it as a DataFrame.

    Checks:
    - Missing weather information and its overlap with missing location
    - Rows where is_cloudy=True but cloud cover=0 (weather API anomaly),
      and how many of those used fallback time 11:00
    - The single 1980 outlier row
    """
    n = len(df)

    # --- Missing weather -------------------------------------------------
    no_weather   = df["temp"].isna() if "temp" in df.columns else pd.Series(False, index=df.index)
    no_lat       = df["latitude"].isna() if "latitude" in df.columns else pd.Series(True, index=df.index)
    no_lon       = df["longitude"].isna() if "longitude" in df.columns else pd.Series(True, index=df.index)
    no_location  = no_lat | no_lon

    n_no_weather          = int(no_weather.sum())
    n_no_weather_no_loc   = int((no_weather & no_location).sum())
    n_no_weather_with_loc = n_no_weather - n_no_weather_no_loc

    # --- is_cloudy=True with clouds=0 ------------------------------------
    if "is_cloudy" in df.columns and "clouds" in df.columns:
        bad_cover          = df["is_cloudy"].eq(True) & df["clouds"].eq(0)
        n_bad_cover        = int(bad_cover.sum())
        if "fallback_dt_used" in df.columns:
            n_bad_fallback = int((bad_cover & df["fallback_dt_used"].eq(True)).sum())
        else:
            n_bad_fallback = "n/a"
    else:
        n_bad_cover    = "n/a"
        n_bad_fallback = "n/a"

    # --- 1980 outlier ----------------------------------------------------
    years   = pd.to_datetime(df["date_taken"], errors="coerce").dt.year
    n_1980  = int(years.eq(1980).sum())

    rows = [
        {"check": "Total rows",                               "count": n,                    "note": ""},
        {"check": "Rows without weather info",                "count": n_no_weather,          "note": f"{100*n_no_weather/n:.1f}% of all rows"},
        {"check": "  → of which: also no location",          "count": n_no_weather_no_loc,   "note": "no coordinates → weather lookup impossible"},
        {"check": "  → of which: have location but no weather", "count": n_no_weather_with_loc, "note": "2 rows; likely too old for weather archive"},
        {"check": "is_cloudy=True AND cloud cover=0",         "count": n_bad_cover,           "note": "weather API anomaly; excluded from weather charts"},
        {"check": "  → of which: used fallback time 11:00",   "count": n_bad_fallback,        "note": "time unknown → may explain wrong hour for API call"},
        {"check": "Rows with date year = 1980",               "count": n_1980,                "note": "outlier; excluded from all charts"},
    ]

    result = pd.DataFrame(rows)
    print(result.to_string(index=False))
    return result


def summary_table(df: pd.DataFrame) -> pd.DataFrame:
    """
    Return a summary DataFrame with four columns (metric / count / missing / pct):
    - Dataset size and date range
    - Geographic diversity (countries, unique lat/lon locations)
    - Completeness for date_taken, time_taken, temp, latitude, longitude
      (these rows include missing count and fill %)
    - Cloud label distribution (4 categories matching _cloud_label logic)
      (these rows have no missing column — counts are mutually exclusive)
    """
    n = len(df)

    def _fill(col):
        return int(df[col].notna().sum()) if col in df.columns else 0

    def _pct(count):
        return round(100 * count / n, 1) if n > 0 else 0.0

    def _completeness_row(label, col):
        filled = _fill(col)
        return {"metric": label, "count": filled, "missing": n - filled, "pct": _pct(filled)}

    date_series = pd.to_datetime(df["date_taken"], errors="coerce")
    date_min = date_series.min()
    date_max = date_series.max()

    unique_countries = df["country"].nunique() if "country" in df.columns else "?"
    if "latitude" in df.columns and "longitude" in df.columns:
        unique_locs = int(df[["latitude", "longitude"]].dropna().drop_duplicates().shape[0])
    else:
        unique_locs = "?"

    t1 = df["cloud_type1"].replace("", pd.NA) if "cloud_type1" in df.columns else pd.Series(pd.NA, index=df.index)
    s1 = df["subtype1"].replace("", pd.NA) if "subtype1" in df.columns else pd.Series(pd.NA, index=df.index)
    is_cloudy = df["is_cloudy"] if "is_cloudy" in df.columns else pd.Series(True, index=df.index)

    n_main     = int(t1.notna().sum())
    n_sub_only = int((t1.isna() & s1.notna() & ~is_cloudy.eq(False)).sum())
    n_no_cloud = int(is_cloudy.eq(False).sum())
    n_unclass  = int((t1.isna() & s1.isna() & ~is_cloudy.eq(False)).sum())

    rows = [
        {"metric": "total rows",        "count": n,                 "missing": "",  "pct": ""},
        {"metric": "date range start",  "count": str(date_min.date()) if pd.notna(date_min) else "?", "missing": "", "pct": ""},
        {"metric": "date range end",    "count": str(date_max.date()) if pd.notna(date_max) else "?", "missing": "", "pct": ""},
        {"metric": "unique countries",  "count": unique_countries,  "missing": "",  "pct": ""},
        {"metric": "unique locations",  "count": unique_locs,       "missing": "",  "pct": ""},
        _completeness_row("date taken",  "date_taken"),
        _completeness_row("time taken",  "time_taken"),
        _completeness_row("temp",        "temp"),
        _completeness_row("latitude",    "latitude"),
        _completeness_row("longitude",   "longitude"),
        {"metric": "— cloud labels —",  "count": "",                "missing": "",  "pct": ""},
        {"metric": "with main type",    "count": n_main,            "missing": "",  "pct": _pct(n_main)},
        {"metric": "subtype only",      "count": n_sub_only,        "missing": "",  "pct": _pct(n_sub_only)},
        {"metric": "no cloud",          "count": n_no_cloud,        "missing": "",  "pct": _pct(n_no_cloud)},
        {"metric": "unclassified",      "count": n_unclass,         "missing": "",  "pct": _pct(n_unclass)},
    ]
    return pd.DataFrame(rows)


def rows_per_year(df: pd.DataFrame) -> plt.Figure:
    """Bar chart: number of rows per year. Excludes the 1980 outlier."""
    standard_style()
    df_f = _filter_valid_year(df)
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
    """Horizontal bar chart: top N countries by row count, with count labels."""
    standard_style()
    df_f = _filter_valid_year(df)
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
            va="center",
            fontsize=11,
        )
    ax.set_xlim(right=x_max * 1.12)
    fig.tight_layout()
    return fig


# ============================================================
# C. Cloud types
# ============================================================

def cloud_type_bar(df: pd.DataFrame) -> plt.Figure:
    """Bar chart: frequency of primary cloud type, sorted descending, with counts on top."""
    standard_style()
    df_f = _filter_valid_year(df)
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
    """Bar chart: top N subtypes (subtype1 + subtype2 combined), with counts on top."""
    standard_style()
    df_f = _filter_valid_year(df)
    s1 = df_f["subtype1"].dropna() if "subtype1" in df_f.columns else pd.Series(dtype=str)
    s2 = df_f["subtype2"].dropna() if "subtype2" in df_f.columns else pd.Series(dtype=str)
    all_subtypes = pd.concat([s1, s2]).str.lower().str.strip()
    counts = all_subtypes.value_counts().head(n)

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
    Diagonal cells (same type on both axes) are shown in grey.
    Only rows where both are filled.
    """
    standard_style()
    df_f = _filter_valid_year(df)
    sub = df_f[df_f["cloud_type1"].notna() & df_f["cloud_type2"].notna()].copy()
    sub["t1"] = sub["cloud_type1"].str.lower().str.strip()
    sub["t2"] = sub["cloud_type2"].str.lower().str.strip()

    types = [c for c in CLOUD_ORDER if c not in ("no cloud", "unclassified")]
    matrix = pd.crosstab(sub["t1"], sub["t2"]).reindex(
        index=types, columns=types, fill_value=0
    )

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

    # Count labels for non-zero cells
    for i in range(len(matrix.index)):
        for j in range(len(matrix.columns)):
            v = matrix.values[i, j]
            if v > 0:
                ax.text(j, i, str(v), ha="center", va="center", fontsize=9)

    # Grey diagonal patches where cloud_type1 == cloud_type2
    cols_list = matrix.columns.tolist()
    for i, t in enumerate(matrix.index):
        if t in cols_list:
            j = cols_list.index(t)
            ax.add_patch(mpatches.Rectangle(
                (j - 0.5, i - 0.5), 1, 1,
                color="#AAAAAA", zorder=2, alpha=0.85,
            ))

    fig.tight_layout()
    return fig


def cooccurrence_cloudtype_subtype(df: pd.DataFrame, n_subtypes: int = 15) -> plt.Figure:
    """
    Heatmap: how often each cloud_type1 co-occurs with each subtype1.
    Only rows where both are filled. Top n_subtypes subtypes on the x-axis.
    """
    standard_style()
    df_f = _filter_valid_year(df)
    sub = df_f[df_f["cloud_type1"].notna() & df_f["subtype1"].notna()].copy()
    sub["t1"] = sub["cloud_type1"].str.lower().str.strip()
    sub["s1"] = sub["subtype1"].str.lower().str.strip()

    top_subs = sub["s1"].value_counts().head(n_subtypes).index.tolist()
    sub = sub[sub["s1"].isin(top_subs)]

    types = [c for c in CLOUD_ORDER if c not in ("no cloud", "unclassified") and c in sub["t1"].unique()]
    matrix = pd.crosstab(sub["t1"], sub["s1"]).reindex(
        index=types, columns=top_subs, fill_value=0
    )

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

def cloud_by_hour(df: pd.DataFrame) -> go.Figure:
    """
    Interactive Plotly line chart: number of cloud observations by hour of day.
    Rows with fallback time 11:00 are excluded (time is unknown for those rows).

    Dropdown has 25 options:
    - 13 cloud-type options  (all cloud types / one specific type), all months combined
    - 12 month options  (all cloud types in that month)
    """
    df_f = _filter_valid_year(_drop_fallback(df))
    df_f = df_f.copy()
    df_f["hour"]  = pd.to_datetime(df_f["time_taken"],  format="%H:%M:%S", errors="coerce").dt.hour
    df_f["month"] = pd.to_datetime(df_f["date_taken"],  errors="coerce").dt.month
    df_f["label"] = _cloud_label(df_f)
    df_f = df_f[df_f["hour"].notna()]

    hours = list(range(24))

    traces = []
    dropdown_buttons = []

    # --- Section 1: by cloud type (all months combined) ---
    type_options = ["all"] + [ct for ct in CLOUD_ORDER if ct != "unclassified"]
    for ct_idx, ct in enumerate(type_options):
        subset  = df_f if ct == "all" else df_f[df_f["label"] == ct]
        counts  = subset.groupby("hour").size().reindex(hours, fill_value=0)
        color   = PALETTE[0] if ct == "all" else CLOUD_TYPE_COLORS.get(ct, PALETTE[0])
        label   = "All cloud types" if ct == "all" else ct.title()
        traces.append(go.Scatter(
            x=hours,
            y=counts.values,
            mode="lines+markers",
            line=dict(color=color, width=2.5),
            marker=dict(size=6),
            name=label,
            visible=(ct_idx == 0),
        ))
        dropdown_buttons.append(dict(
            label=f"☁ {label}",
            method="update",
            args=[{"visible": [False] * (len(type_options) + 12)},
                  {"title.text": f"Observations by hour  —  {label}  (all months)"}],
        ))
        dropdown_buttons[-1]["args"][0]["visible"] = [j == ct_idx for j in range(len(type_options) + 12)]

    # --- Section 2: by month (all cloud types) ---
    for m in range(1, 13):
        month_name = calendar.month_name[m]
        subset  = df_f[df_f["month"] == m]
        counts  = subset.groupby("hour").size().reindex(hours, fill_value=0)
        color   = PALETTE[(m - 1) % len(PALETTE)]
        trace_idx = len(type_options) + (m - 1)
        traces.append(go.Scatter(
            x=hours,
            y=counts.values,
            mode="lines+markers",
            line=dict(color=color, width=2.5),
            marker=dict(size=6),
            name=month_name,
            visible=False,
        ))
        dropdown_buttons.append(dict(
            label=f"📅 {month_name}",
            method="update",
            args=[
                {"visible": [j == trace_idx for j in range(len(type_options) + 12)]},
                {"title.text": f"Observations by hour  —  {month_name}  (all cloud types)"},
            ],
        ))

    fig = go.Figure(data=traces)
    fig.update_layout(
        updatemenus=[dict(
            buttons=dropdown_buttons,
            direction="down",
            x=0.01, xanchor="left",
            y=1.22, yanchor="top",
            showactive=True,
            bgcolor="white",
            bordercolor="#CCCCCC",
        )],
        xaxis=dict(
            title="Hour of day",
            tickmode="linear",
            dtick=2,
            range=[-0.5, 23.5],
        ),
        yaxis_title="Number of observations",
        title="Observations by hour of day  —  All cloud types  (all months)",
        height=500,
        showlegend=False,
        margin=dict(t=100),
    )
    return fig


# ============================================================
# E. Weather distributions
# ============================================================

def weather_histograms_interactive(df: pd.DataFrame) -> go.Figure:
    """
    Interactive Plotly histogram: choose the weather variable from a dropdown.
    Shows three overlapping distributions: All / Cloudy / No cloud.

    Rows where is_cloudy=True AND clouds=0 are excluded (weather API anomaly).
    Variables: temp, humidity, pressure, dew_point, wind_speed, rain_1h, snow_1h.
    Excluded: all cloud cover columns, wind_gust, wind_deg, visibility (empty), uvi (empty).
    """
    df_f = _filter_valid_year(_filter_good_weather(df))

    groups = [
        ("All",      df_f,                                    PALETTE[3]),
        ("Cloudy",   df_f[df_f["is_cloudy"].eq(True)],        PALETTE[0]),
        ("No cloud", df_f[df_f["is_cloudy"].eq(False)],       NO_CLOUD),
    ]

    valid_vars = [
        (col, lbl) for col, lbl in WEATHER_VARS
        if col in df_f.columns and df_f[col].notna().any()
    ]

    n_groups = len(groups)
    total_traces = len(valid_vars) * n_groups

    fig = go.Figure()
    for v_idx, (col, vlabel) in enumerate(valid_vars):
        for g_idx, (gname, gdf, gcolor) in enumerate(groups):
            fig.add_trace(go.Histogram(
                x=gdf[col].dropna(),
                name=gname,
                marker_color=gcolor,
                opacity=0.65,
                nbinsx=50,
                visible=(v_idx == 0),
                legendgroup=gname,
                showlegend=(v_idx == 0),
            ))

    buttons = []
    for v_idx, (col, vlabel) in enumerate(valid_vars):
        visible = [v_idx * n_groups <= i < (v_idx + 1) * n_groups for i in range(total_traces)]
        buttons.append(dict(
            label=vlabel,
            method="update",
            args=[
                {"visible": visible},
                {"xaxis.title.text": vlabel, "title.text": f"Distribution: {vlabel}"},
            ],
        ))

    first_label = valid_vars[0][1] if valid_vars else ""
    fig.update_layout(
        updatemenus=[dict(
            buttons=buttons,
            direction="down",
            x=0.01, xanchor="left",
            y=1.18, yanchor="top",
            showactive=True,
            bgcolor="white",
            bordercolor="#CCCCCC",
        )],
        barmode="overlay",
        xaxis_title=first_label,
        yaxis_title="Count",
        title=f"Distribution: {first_label}",
        height=480,
        legend=dict(title="Category"),
        margin=dict(t=100),
    )
    return fig


def boxplots_interactive(df: pd.DataFrame) -> go.Figure:
    """
    Interactive Plotly box plot: choose the weather variable from a dropdown.
    Shows three side-by-side boxes: All / Cloudy / No cloud.

    Rows where is_cloudy=True AND clouds=0 are excluded (weather API anomaly).
    """
    df_f = _filter_valid_year(_filter_good_weather(df))

    groups = [
        ("All",      df_f,                                    PALETTE[3]),
        ("Cloudy",   df_f[df_f["is_cloudy"].eq(True)],        PALETTE[0]),
        ("No cloud", df_f[df_f["is_cloudy"].eq(False)],       NO_CLOUD),
    ]

    valid_vars = [
        (col, lbl) for col, lbl in WEATHER_VARS
        if col in df_f.columns and df_f[col].notna().any()
    ]

    n_groups = len(groups)
    total_traces = len(valid_vars) * n_groups

    fig = go.Figure()
    for v_idx, (col, vlabel) in enumerate(valid_vars):
        for g_idx, (gname, gdf, gcolor) in enumerate(groups):
            fig.add_trace(go.Box(
                y=gdf[col].dropna(),
                name=gname,
                marker_color=gcolor,
                visible=(v_idx == 0),
                legendgroup=gname,
                showlegend=(v_idx == 0),
                boxmean=True,
            ))

    buttons = []
    for v_idx, (col, vlabel) in enumerate(valid_vars):
        visible = [v_idx * n_groups <= i < (v_idx + 1) * n_groups for i in range(total_traces)]
        buttons.append(dict(
            label=vlabel,
            method="update",
            args=[
                {"visible": visible},
                {"yaxis.title.text": vlabel,
                 "title.text": f"{vlabel}  —  All vs Cloudy vs No cloud"},
            ],
        ))

    first_label = valid_vars[0][1] if valid_vars else ""
    fig.update_layout(
        updatemenus=[dict(
            buttons=buttons,
            direction="down",
            x=0.01, xanchor="left",
            y=1.18, yanchor="top",
            showactive=True,
            bgcolor="white",
            bordercolor="#CCCCCC",
        )],
        yaxis_title=first_label,
        title=f"{first_label}  —  All vs Cloudy vs No cloud",
        height=520,
        legend=dict(title="Category"),
        boxmode="group",
        margin=dict(t=100),
    )
    return fig


def dew_spread_by_altitude(df: pd.DataFrame) -> plt.Figure:
    """
    Box plot: dew point spread (temp − dew_point) grouped by cloud altitude level.
    High / mid / low cloud groups shown side by side; individual cloud types as separate boxes.
    Rows where is_cloudy=True AND clouds=0 are excluded.
    """
    standard_style()
    df_f = _filter_valid_year(_filter_good_weather(df))
    sub = df_f[df_f["temp"].notna() & df_f["dew_point"].notna()].copy()
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
        pos_current += 1.5  # gap between altitude groups

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
    ax.set_title("Dew point spread by cloud altitude group\n(small spread = air near saturation = more cloud formation)")

    # Vertical separators between groups
    for sep_x in separator_positions[:-1]:
        ax.axvline(sep_x, color="#DDDDDD", linewidth=1.2, zorder=0)

    # Legend for altitude groups
    patches = [
        mpatches.Patch(facecolor=ALTITUDE_COLORS[k], alpha=0.85, label=ALTITUDE_LABELS[k])
        for k in ["high", "mid", "low"] if k in group_mid_positions
    ]
    ax.legend(handles=patches, loc="upper right", frameon=False)
    fig.tight_layout()
    return fig


def weather_code_vs_cloudtype(df: pd.DataFrame) -> go.Figure:
    """
    Interactive Plotly stacked bar chart: relationship between weather conditions
    (broad OWM code groups) and primary cloud type.

    Dropdown toggles between two views:
    - 'By cloud type'       → x = cloud type, stacked = weather condition (% within each type)
    - 'By weather condition' → x = weather condition, stacked = cloud type (% within each condition)

    Rows where is_cloudy=True AND clouds=0 are excluded.
    """
    df_f = _filter_valid_year(_filter_good_weather(df))
    sub = df_f[df_f["weather_code"].notna() & df_f["cloud_type1"].notna()].copy()
    sub["weather_group"] = sub["weather_code"].apply(_owm_weather_group)
    sub["ct"] = sub["cloud_type1"].str.lower().str.strip()

    ct_order = [c for c in CLOUD_ORDER if c not in ("no cloud", "unclassified") and c in sub["ct"].unique()]
    wg_order  = sub["weather_group"].value_counts().index.tolist()  # most frequent first

    # Normalised crosstabs (percentage)
    ct_wg = pd.crosstab(sub["ct"], sub["weather_group"], normalize="index") * 100
    ct_wg = ct_wg.reindex(index=ct_order, fill_value=0)

    wg_ct = pd.crosstab(sub["weather_group"], sub["ct"], normalize="index") * 100
    wg_ct = wg_ct.reindex(index=wg_order, fill_value=0)

    # Define a fixed color palette for weather groups
    wg_colors = [
        "#FFD700", "#87CEEB", "#708090", "#4B0082",
        "#6495ED", "#1E90FF", "#B0E0E6", "#C0C0C0", "#D3D3D3",
    ]

    # View 1 traces: one per weather group (bars = cloud types on x)
    traces_v1 = []
    for i, wg in enumerate(wg_order):
        vals = ct_wg[wg].values if wg in ct_wg.columns else np.zeros(len(ct_order))
        traces_v1.append(go.Bar(
            x=ct_order,
            y=vals,
            name=wg,
            marker_color=wg_colors[i % len(wg_colors)],
            visible=True,
        ))

    # View 2 traces: one per cloud type (bars = weather groups on x)
    traces_v2 = []
    for ct in ct_order:
        vals = wg_ct[ct].values if ct in wg_ct.columns else np.zeros(len(wg_order))
        traces_v2.append(go.Bar(
            x=wg_order,
            y=vals,
            name=ct.title(),
            marker_color=CLOUD_TYPE_COLORS.get(ct, NO_CLOUD),
            visible=False,
        ))

    n_v1 = len(traces_v1)
    n_v2 = len(traces_v2)

    buttons = [
        dict(
            label="By cloud type",
            method="update",
            args=[
                {"visible": [True] * n_v1 + [False] * n_v2},
                {"xaxis.title.text": "Cloud type",
                 "title.text": "Weather conditions by cloud type  (% within each type)",
                 "legend.title.text": "Weather condition"},
            ],
        ),
        dict(
            label="By weather condition",
            method="update",
            args=[
                {"visible": [False] * n_v1 + [True] * n_v2},
                {"xaxis.title.text": "Weather condition",
                 "title.text": "Cloud types by weather condition  (% within each condition)",
                 "legend.title.text": "Cloud type"},
            ],
        ),
    ]

    fig = go.Figure(data=traces_v1 + traces_v2)
    fig.update_layout(
        updatemenus=[dict(
            buttons=buttons,
            direction="down",
            x=0.01, xanchor="left",
            y=1.15, yanchor="top",
            showactive=True,
            bgcolor="white",
            bordercolor="#CCCCCC",
        )],
        barmode="stack",
        xaxis_title="Cloud type",
        yaxis_title="Percentage (%)",
        title="Weather conditions by cloud type  (% within each type)",
        legend=dict(title="Weather condition"),
        height=540,
        margin=dict(t=100),
    )
    return fig


# ============================================================
# F. Cloud type vs weather — scatter plots
# ============================================================

def scatter_cape_vs_clouds(df: pd.DataFrame) -> plt.Figure:
    """
    Scatter: CAPE (x) vs total cloud cover (y), colored by cloud_type1.
    Note: the 'cape' column is not present in the current dataset;
    this function will produce an empty chart if that column is missing.
    """
    standard_style()
    df_f = _filter_valid_year(_filter_good_weather(df))
    if "cape" not in df_f.columns or "clouds" not in df_f.columns:
        fig, ax = plt.subplots()
        ax.set_title("CAPE vs cloud cover  (cape column not available in dataset)")
        return fig

    sub = df_f[df_f["cape"].notna() & df_f["clouds"].notna()].copy()
    sub["label"] = _cloud_label(sub)

    fig, ax = plt.subplots(figsize=(10, 6))
    for ct in CLOUD_ORDER:
        group = sub[sub["label"] == ct]
        if group.empty:
            continue
        ax.scatter(group["cape"], group["clouds"],
                   color=CLOUD_TYPE_COLORS.get(ct, NO_CLOUD),
                   label=ct, alpha=0.55, s=30, linewidths=0)
    ax.set_xlabel("CAPE (J/kg) — atmospheric instability")
    ax.set_ylabel("Total cloud cover (%)")
    ax.set_title("CAPE vs cloud cover by cloud type")
    ax.legend(bbox_to_anchor=(1.01, 1), loc="upper left", fontsize=11)
    fig.tight_layout()
    return fig


def scatter_dew_spread_by_cloudtype(df: pd.DataFrame) -> plt.Figure:
    """
    Box plot: dew point spread (temp − dew_point) by cloud type.
    A small spread means the air is near saturation → cloud formation.
    Rows where is_cloudy=True AND clouds=0 are excluded.
    """
    standard_style()
    df_f = _filter_valid_year(_filter_good_weather(df))
    sub = df_f[df_f["temp"].notna() & df_f["dew_point"].notna()].copy()
    sub["spread"] = sub["temp"] - sub["dew_point"]
    sub["label"]  = _cloud_label(sub)

    ordered = [c for c in CLOUD_ORDER if c in sub["label"].unique()]
    data_by_type = [sub.loc[sub["label"] == ct, "spread"].values for ct in ordered]
    colors = _color_list(ordered)

    fig, ax = plt.subplots(figsize=(12, 5))
    bp = ax.boxplot(data_by_type, patch_artist=True,
                    medianprops=dict(color="white", linewidth=2))
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.85)
    ax.set_xticks(range(1, len(ordered) + 1))
    ax.set_xticklabels(ordered, rotation=40, ha="right")
    ax.set_ylabel("Temp − Dew point  (°C)")
    ax.set_title("Dew point spread by cloud type\n(small spread = near saturation = more cloud)")
    ax.axhline(0, color="gray", linestyle="--", linewidth=1)
    fig.tight_layout()
    return fig


def scatter_low_vs_high_cover(df: pd.DataFrame) -> plt.Figure:
    """
    Scatter: low cloud cover (x) vs high cloud cover (y), colored by cloud_type1.
    Low clouds = stratus family. High clouds = cirrus family. Overlap = mixed.
    Rows where is_cloudy=True AND clouds=0 are excluded.
    """
    standard_style()
    df_f = _filter_valid_year(_filter_good_weather(df))
    sub = df_f[df_f["clouds_low"].notna() & df_f["clouds_high"].notna()].copy()
    sub["label"] = _cloud_label(sub)

    fig, ax = plt.subplots(figsize=(10, 6))
    for ct in CLOUD_ORDER:
        group = sub[sub["label"] == ct]
        if group.empty:
            continue
        ax.scatter(group["clouds_low"], group["clouds_high"],
                   color=CLOUD_TYPE_COLORS.get(ct, NO_CLOUD),
                   label=ct, alpha=0.55, s=30, linewidths=0)
    ax.set_xlabel("Low cloud cover (%)")
    ax.set_ylabel("High cloud cover (%)")
    ax.set_title("Low vs high cloud cover by cloud type")
    ax.legend(bbox_to_anchor=(1.01, 1), loc="upper left", fontsize=11)
    fig.tight_layout()
    return fig


def scatter_humidity_dew_by_type(df: pd.DataFrame) -> go.Figure:
    """
    Interactive Plotly scatter: relative humidity (x) vs dew point (y).
    Dropdown selects one cloud type at a time.
    'All (overview)' shows all points in neutral grey.
    Rows with fallback time and is_cloudy=True/clouds=0 anomalies are excluded.
    """
    df_f = _filter_valid_year(_filter_good_weather(_drop_fallback(df)))
    sub = df_f[df_f["humidity"].notna() & df_f["dew_point"].notna()].copy()
    sub["label"] = _cloud_label(sub)

    type_options = ["all"] + [ct for ct in CLOUD_ORDER if ct not in ("unclassified",)]

    traces = []
    for ct in type_options:
        if ct == "all":
            subset = sub
            color  = "#AAAAAA"
            name   = "All (overview)"
        else:
            subset = sub[sub["label"] == ct]
            color  = CLOUD_TYPE_COLORS.get(ct, NO_CLOUD)
            name   = ct.title()
        traces.append(go.Scatter(
            x=subset["humidity"],
            y=subset["dew_point"],
            mode="markers",
            marker=dict(color=color, size=4, opacity=0.4),
            name=name,
            visible=(ct == type_options[1]),  # default: first cloud type
        ))

    n = len(type_options)
    buttons = []
    for i, ct in enumerate(type_options):
        label = "All (overview)" if ct == "all" else ct.title()
        buttons.append(dict(
            label=label,
            method="update",
            args=[
                {"visible": [j == i for j in range(n)]},
                {"title.text": f"Humidity vs Dew Point  —  {label}"},
            ],
        ))

    first = type_options[1].title()
    fig = go.Figure(data=traces)
    fig.update_layout(
        updatemenus=[dict(
            buttons=buttons, direction="down",
            x=0.01, xanchor="left", y=1.18, yanchor="top",
            showactive=True, bgcolor="white", bordercolor="#CCCCCC",
        )],
        xaxis_title="Relative Humidity (%)",
        yaxis_title="Dew Point (°C)",
        title=f"Humidity vs Dew Point  —  {first}",
        height=550,
        showlegend=False,
        margin=dict(t=100),
    )
    return fig


def scatter_humidity_dew_cloudy(df: pd.DataFrame) -> go.Figure:
    """
    Plotly scatter: relative humidity (x) vs dew point (y).
    Two colours: Cloudy (SAGE green) vs No cloud (grey).
    Rows where is_cloudy=True AND clouds=0 are excluded.
    """
    df_f = _filter_valid_year(_filter_good_weather(df))
    sub = df_f[df_f["humidity"].notna() & df_f["dew_point"].notna()].copy()

    fig = go.Figure()
    for is_cl, name, color in [
        (True,  "Cloudy",   PALETTE[0]),
        (False, "No cloud", NO_CLOUD),
    ]:
        s = sub[sub["is_cloudy"].eq(is_cl)]
        fig.add_trace(go.Scatter(
            x=s["humidity"], y=s["dew_point"],
            mode="markers",
            marker=dict(color=color, size=4, opacity=0.35),
            name=name,
        ))

    fig.update_layout(
        xaxis_title="Relative Humidity (%)",
        yaxis_title="Dew Point (°C)",
        title="Humidity vs Dew Point  —  Cloudy vs No cloud",
        legend=dict(title="Category"),
        height=520,
    )
    return fig


def scatter_dew_pressure_by_type(df: pd.DataFrame) -> go.Figure:
    """
    Interactive Plotly scatter: dew point (x) vs pressure (y).
    Dropdown selects one cloud type at a time.
    'All (overview)' shows all points in neutral grey.
    Rows with fallback time and is_cloudy=True/clouds=0 anomalies are excluded.
    """
    df_f = _filter_valid_year(_filter_good_weather(_drop_fallback(df)))
    sub = df_f[df_f["dew_point"].notna() & df_f["pressure"].notna()].copy()
    sub["label"] = _cloud_label(sub)

    type_options = ["all"] + [ct for ct in CLOUD_ORDER if ct not in ("unclassified",)]

    traces = []
    for ct in type_options:
        if ct == "all":
            subset = sub
            color  = "#AAAAAA"
            name   = "All (overview)"
        else:
            subset = sub[sub["label"] == ct]
            color  = CLOUD_TYPE_COLORS.get(ct, NO_CLOUD)
            name   = ct.title()
        traces.append(go.Scatter(
            x=subset["dew_point"],
            y=subset["pressure"],
            mode="markers",
            marker=dict(color=color, size=4, opacity=0.4),
            name=name,
            visible=(ct == type_options[1]),
        ))

    n = len(type_options)
    buttons = []
    for i, ct in enumerate(type_options):
        label = "All (overview)" if ct == "all" else ct.title()
        buttons.append(dict(
            label=label,
            method="update",
            args=[
                {"visible": [j == i for j in range(n)]},
                {"title.text": f"Dew Point vs Pressure  —  {label}"},
            ],
        ))

    first = type_options[1].title()
    fig = go.Figure(data=traces)
    fig.update_layout(
        updatemenus=[dict(
            buttons=buttons, direction="down",
            x=0.01, xanchor="left", y=1.18, yanchor="top",
            showactive=True, bgcolor="white", bordercolor="#CCCCCC",
        )],
        xaxis_title="Dew Point (°C)",
        yaxis_title="Pressure (hPa)",
        title=f"Dew Point vs Pressure  —  {first}",
        height=550,
        showlegend=False,
        margin=dict(t=100),
    )
    return fig


def scatter_dew_pressure_cloudy(df: pd.DataFrame) -> go.Figure:
    """
    Plotly scatter: dew point (x) vs pressure (y).
    Two colours: Cloudy (SAGE green) vs No cloud (grey).
    Rows where is_cloudy=True AND clouds=0 are excluded.
    """
    df_f = _filter_valid_year(_filter_good_weather(df))
    sub = df_f[df_f["dew_point"].notna() & df_f["pressure"].notna()].copy()

    fig = go.Figure()
    for is_cl, name, color in [
        (True,  "Cloudy",   PALETTE[0]),
        (False, "No cloud", NO_CLOUD),
    ]:
        s = sub[sub["is_cloudy"].eq(is_cl)]
        fig.add_trace(go.Scatter(
            x=s["dew_point"], y=s["pressure"],
            mode="markers",
            marker=dict(color=color, size=4, opacity=0.35),
            name=name,
        ))

    fig.update_layout(
        xaxis_title="Dew Point (°C)",
        yaxis_title="Pressure (hPa)",
        title="Dew Point vs Pressure  —  Cloudy vs No cloud",
        legend=dict(title="Category"),
        height=520,
    )
    return fig
