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
"""

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd
import plotly.express as px

from verycloudy.styling import standard_style, CLOUD_TYPE_COLORS, NO_CLOUD, PALETTE

# Order used consistently across all charts
CLOUD_ORDER = [
    "cumulus", "cumulonimbus", "stratocumulus", "stratus",
    "nimbostratus", "altostratus", "altocumulus",
    "cirrus", "cirrostratus", "cirrocumulus",
    "no cloud",
]


def _cloud_label(df: pd.DataFrame) -> pd.Series:
    """
    Return a Series with the primary cloud label per row.
    Rows with no cloud_type1 are labelled 'no cloud'.
    """
    return df["cloud_type1"].fillna("no cloud").str.lower().str.strip()


def _color_list(labels: list[str]) -> list[str]:
    """Map a list of cloud type labels to hex colors."""
    return [CLOUD_TYPE_COLORS.get(l, NO_CLOUD) for l in labels]


# ============================================================
# A. Dataset overview
# ============================================================

def summary_table(df: pd.DataFrame) -> pd.DataFrame:
    """
    Return a small summary DataFrame: total rows, date range,
    and fill rate for key columns.
    """
    key_cols = [
        "latitude", "longitude", "date_taken", "time_taken",
        "temp", "clouds", "cloud_type1",
    ]
    rows = []
    for col in key_cols:
        if col in df.columns:
            filled = df[col].notna().sum()
            rows.append({
                "column":    col,
                "filled":    filled,
                "missing":   len(df) - filled,
                "fill_pct":  round(100 * filled / len(df), 1),
            })

    summary = pd.DataFrame(rows)

    # Prepend general stats
    date_min = pd.to_datetime(df["date_taken"], errors="coerce").min()
    date_max = pd.to_datetime(df["date_taken"], errors="coerce").max()
    general = pd.DataFrame([
        {"column": "total rows",    "filled": len(df),              "missing": 0,   "fill_pct": 100.0},
        {"column": "date range",    "filled": str(date_min.date()) if pd.notna(date_min) else "?",
                                    "missing": "",  "fill_pct": ""},
        {"column": "date range end","filled": str(date_max.date()) if pd.notna(date_max) else "?",
                                    "missing": "",  "fill_pct": ""},
        {"column": "unique countries", "filled": df["country"].nunique() if "country" in df.columns else "?",
                                    "missing": "", "fill_pct": ""},
    ])
    return pd.concat([general, summary], ignore_index=True)


def completeness_bar(df: pd.DataFrame) -> plt.Figure:
    """Horizontal bar chart: fill % for key columns."""
    standard_style()
    cols = {
        "location (lat/lon)": "latitude",
        "date taken":         "date_taken",
        "time taken":         "time_taken",
        "temperature":        "temp",
        "cloud cover":        "clouds",
        "cloud type 1":       "cloud_type1",
        "subtype 1":          "subtype1",
    }
    labels, pcts = [], []
    for label, col in cols.items():
        if col in df.columns:
            labels.append(label)
            pcts.append(100 * df[col].notna().mean())

    fig, ax = plt.subplots(figsize=(9, 4))
    bars = ax.barh(labels, pcts, color=PALETTE[0])
    ax.set_xlim(0, 110)
    ax.set_xlabel("% filled")
    ax.set_title("Dataset completeness")
    for bar, pct in zip(bars, pcts):
        ax.text(pct + 1, bar.get_y() + bar.get_height() / 2,
                f"{pct:.0f}%", va="center", fontsize=12)
    fig.tight_layout()
    return fig


def rows_per_year(df: pd.DataFrame) -> plt.Figure:
    """Bar chart: number of rows per year."""
    standard_style()
    years = pd.to_datetime(df["date_taken"], errors="coerce").dt.year.dropna().astype(int)
    counts = years.value_counts().sort_index()

    fig, ax = plt.subplots()
    ax.bar(counts.index, counts.values, color=PALETTE[3], width=0.7)
    ax.set_xlabel("Year")
    ax.set_ylabel("Number of rows")
    ax.set_title("Rows per year")
    ax.set_xticks(counts.index)
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    return fig


# ============================================================
# B. Geographic spread
# ============================================================

def country_counts(df: pd.DataFrame) -> pd.Series:
    """Value counts of the country column."""
    return df["country"].value_counts()


def top_countries_bar(df: pd.DataFrame, n: int = 20) -> plt.Figure:
    """Horizontal bar chart: top N countries by row count."""
    standard_style()
    counts = df["country"].value_counts().head(n)

    fig, ax = plt.subplots(figsize=(9, max(4, n * 0.35)))
    ax.barh(counts.index[::-1], counts.values[::-1], color=PALETTE[2])
    ax.set_xlabel("Number of rows")
    ax.set_title(f"Top {n} countries")
    fig.tight_layout()
    return fig


def world_choropleth(df: pd.DataFrame):
    """
    Plotly choropleth: rows per country.
    Returns a plotly Figure (call fig.show() in the notebook).
    """
    counts = df["country"].value_counts().reset_index()
    counts.columns = ["iso_alpha", "count"]

    fig = px.choropleth(
        counts,
        locations="iso_alpha",
        color="count",
        color_continuous_scale=[
            [0.0, "#f0ede8"],
            [0.3, "#D4A373"],
            [0.6, "#B8860B"],
            [1.0, "#556B2F"],
        ],
        title="Geographic spread — rows per country",
        labels={"count": "rows"},
    )
    fig.update_layout(
        coloraxis_colorbar=dict(title="rows"),
        margin=dict(l=0, r=0, t=40, b=0),
    )
    return fig


# ============================================================
# C. Cloud types
# ============================================================

def cloud_type_bar(df: pd.DataFrame) -> plt.Figure:
    """Bar chart: frequency of primary cloud type (cloud_type1)."""
    standard_style()
    labels = _cloud_label(df)
    counts = labels.value_counts()
    # Sort by CLOUD_ORDER, then any remainder alphabetically
    ordered = [c for c in CLOUD_ORDER if c in counts.index]
    ordered += sorted([c for c in counts.index if c not in ordered])
    counts = counts.reindex(ordered).dropna()

    colors = _color_list(counts.index.tolist())
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.bar(counts.index, counts.values, color=colors, width=0.7)
    ax.set_xlabel("Cloud type")
    ax.set_ylabel("Count")
    ax.set_title("Frequency of primary cloud type")
    ax.tick_params(axis="x", rotation=40)
    fig.tight_layout()
    return fig


def subtype_bar(df: pd.DataFrame, n: int = 15) -> plt.Figure:
    """Bar chart: top N subtypes (subtype1 + subtype2 combined)."""
    standard_style()
    s1 = df["subtype1"].dropna() if "subtype1" in df.columns else pd.Series(dtype=str)
    s2 = df["subtype2"].dropna() if "subtype2" in df.columns else pd.Series(dtype=str)
    all_subtypes = pd.concat([s1, s2]).str.lower().str.strip()
    counts = all_subtypes.value_counts().head(n)

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.bar(counts.index, counts.values, color=PALETTE[4], width=0.7)
    ax.set_xlabel("Subtype")
    ax.set_ylabel("Count")
    ax.set_title(f"Top {n} cloud subtypes")
    ax.tick_params(axis="x", rotation=40)
    fig.tight_layout()
    return fig


def cooccurrence_heatmap(df: pd.DataFrame) -> plt.Figure:
    """
    Heatmap: how often cloud_type1 co-occurs with cloud_type2.
    Only rows where both are filled.
    """
    standard_style()
    sub = df[df["cloud_type1"].notna() & df["cloud_type2"].notna()].copy()
    sub["t1"] = sub["cloud_type1"].str.lower().str.strip()
    sub["t2"] = sub["cloud_type2"].str.lower().str.strip()

    types = [c for c in CLOUD_ORDER if c != "no cloud"]
    matrix = pd.crosstab(sub["t1"], sub["t2"]).reindex(
        index=types, columns=types, fill_value=0
    )

    fig, ax = plt.subplots(figsize=(10, 8))
    im = ax.imshow(matrix.values, cmap="YlOrBr", aspect="auto")
    ax.set_xticks(range(len(matrix.columns)))
    ax.set_yticks(range(len(matrix.index)))
    ax.set_xticklabels(matrix.columns, rotation=45, ha="right")
    ax.set_yticklabels(matrix.index)
    ax.set_title("Co-occurrence: cloud_type1 vs cloud_type2")
    ax.set_xlabel("cloud_type2")
    ax.set_ylabel("cloud_type1")
    plt.colorbar(im, ax=ax, shrink=0.7, label="count")

    for i in range(len(matrix.index)):
        for j in range(len(matrix.columns)):
            v = matrix.values[i, j]
            if v > 0:
                ax.text(j, i, str(v), ha="center", va="center", fontsize=9)
    fig.tight_layout()
    return fig


# ============================================================
# D. Weather distributions
# ============================================================

def weather_histograms(df: pd.DataFrame) -> plt.Figure:
    """Grid of histograms for key weather variables."""
    standard_style()
    variables = [
        ("temp",       "Temperature (°C)"),
        ("humidity",   "Humidity (%)"),
        ("pressure",   "Pressure (hPa)"),
        ("clouds",     "Cloud cover (%)"),
        ("cape",       "CAPE (J/kg)"),
        ("wind_speed", "Wind speed (km/h)"),
    ]
    fig, axes = plt.subplots(2, 3, figsize=(14, 8))
    for ax, (col, label) in zip(axes.flat, variables):
        data = df[col].dropna() if col in df.columns else pd.Series(dtype=float)
        if data.empty:
            ax.set_visible(False)
            continue
        ax.hist(data, bins=40, color=PALETTE[0], edgecolor="white", linewidth=0.3)
        ax.set_xlabel(label)
        ax.set_ylabel("Count")
        ax.set_title(label)
    fig.suptitle("Weather variable distributions", y=1.01)
    fig.tight_layout()
    return fig


def boxplots_by_cloudtype(df: pd.DataFrame, variable: str) -> plt.Figure:
    """Box plot: weather variable split by primary cloud type."""
    standard_style()
    if variable not in df.columns:
        raise ValueError(f"Column '{variable}' not found in DataFrame.")

    labels = _cloud_label(df)
    ordered = [c for c in CLOUD_ORDER if c in labels.unique()]

    data_by_type = [df.loc[labels == ct, variable].dropna().values for ct in ordered]
    colors = _color_list(ordered)

    fig, ax = plt.subplots(figsize=(12, 5))
    bp = ax.boxplot(data_by_type, patch_artist=True, notch=False,
                    medianprops=dict(color="white", linewidth=2))
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.85)
    ax.set_xticks(range(1, len(ordered) + 1))
    ax.set_xticklabels(ordered, rotation=40, ha="right")
    ax.set_ylabel(variable)
    ax.set_title(f"{variable} by cloud type")
    fig.tight_layout()
    return fig


# ============================================================
# E. Cloud type vs weather — exam demo scatter plots
# ============================================================

def scatter_cape_vs_clouds(df: pd.DataFrame) -> plt.Figure:
    """
    Scatter: CAPE (x) vs total cloud cover (y), colored by cloud_type1.
    High CAPE + high cloud cover → convective clouds (cumulus, cumulonimbus).
    Low CAPE + high cloud cover → stratiform (stratus, nimbostratus).
    """
    standard_style()
    sub = df[df["cape"].notna() & df["clouds"].notna()].copy()
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
    Replaces the lapse-rate chart (pressure-level temps unavailable in archive).
    """
    standard_style()
    sub = df[df["temp"].notna() & df["dew_point"].notna()].copy()
    sub["spread"] = sub["temp"] - sub["dew_point"]
    sub["label"] = _cloud_label(sub)

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
    """
    standard_style()
    sub = df[df["clouds_low"].notna() & df["clouds_high"].notna()].copy()
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


def scatter_humidity_dew(df: pd.DataFrame) -> plt.Figure:
    """
    Scatter: relative humidity (x) vs dew point (y), colored by cloud_type1.
    Dew point spread narrows as clouds form — useful to show stratiform grouping.
    """
    standard_style()
    sub = df[df["humidity"].notna() & df["dew_point"].notna()].copy()
    sub["label"] = _cloud_label(sub)

    fig, ax = plt.subplots(figsize=(10, 6))
    for ct in CLOUD_ORDER:
        group = sub[sub["label"] == ct]
        if group.empty:
            continue
        ax.scatter(group["humidity"], group["dew_point"],
                   color=CLOUD_TYPE_COLORS.get(ct, NO_CLOUD),
                   label=ct, alpha=0.55, s=30, linewidths=0)
    ax.set_xlabel("Relative humidity (%)")
    ax.set_ylabel("Dew point (°C)")
    ax.set_title("Humidity vs dew point by cloud type")
    ax.legend(bbox_to_anchor=(1.01, 1), loc="upper left", fontsize=11)
    fig.tight_layout()
    return fig
