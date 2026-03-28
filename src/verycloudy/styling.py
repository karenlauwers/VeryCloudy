import matplotlib as mpl
import matplotlib.pyplot as plt

# --- Professional muted palette — 11 clearly distinct hues ---
# Designed for cloud type labelling: 10 genera + 1 "no cloud" neutral.
# Hues are spread across the full color wheel while staying earthy/muted.

SAGE        = '#6B8E7F'   # muted teal-green       → cumulus
GOLDENROD   = '#B8860B'   # deep golden yellow      → cumulonimbus
DUSTY_ROSE  = '#C27A7A'   # muted rose-red          → stratus
SLATE_BLUE  = '#5B7FA6'   # medium steel blue       → stratocumulus
OLIVE       = '#6B7A3A'   # olive green             → altostratus
TERRACOTTA  = '#B8714A'   # warm terracotta orange  → altocumulus
LAVENDER    = '#8B7BAD'   # soft violet             → cirrus
CADET       = '#4F8C8C'   # deep teal               → cirrostratus
SIENNA      = '#9C6B3C'   # warm brown              → cirrocumulus
FERN        = '#4E7C59'   # forest green            → nimbostratus
NO_CLOUD    = '#A8A8A8'   # neutral gray            → no cloud (negative class)

PALETTE = [
    SAGE, GOLDENROD, DUSTY_ROSE, SLATE_BLUE, OLIVE,
    TERRACOTTA, LAVENDER, CADET, SIENNA, FERN, NO_CLOUD,
]

# Mapping cloud type → color (for consistent coloring across all charts)
CLOUD_TYPE_COLORS = {
    "cumulus":       SAGE,
    "cumulonimbus":  GOLDENROD,
    "stratus":       DUSTY_ROSE,
    "stratocumulus": SLATE_BLUE,
    "altostratus":   OLIVE,
    "altocumulus":   TERRACOTTA,
    "cirrus":        LAVENDER,
    "cirrostratus":  CADET,
    "cirrocumulus":  SIENNA,
    "nimbostratus":  FERN,
    "no cloud":      NO_CLOUD,
}

# --- Statistical reference line colors ---
MEAN_COLOR = '#CC0000'
MEDIAN_COLOR = '#E04040'
P25_COLOR = '#D2691E'
P75_COLOR = '#E8820C'
PVALUE_COLOR = '#FF6347'


def standard_style():
    # Remove chart junk
    mpl.rcParams['axes.spines.right'] = False
    mpl.rcParams['axes.spines.top'] = False

    # Figure size
    mpl.rcParams['figure.figsize'] = (10, 5)

    # Color cycle — 11 distinct hues, one per cloud type + no-cloud
    mpl.rcParams['axes.prop_cycle'] = plt.cycler(color=PALETTE)

    # Lines: somewhat thicker than default (1.5)
    mpl.rcParams['lines.linewidth'] = 2.5
    mpl.rcParams['lines.markersize'] = 9

    # Font sizes: all comfortably above defaults for readability
    mpl.rcParams['font.size'] = 14
    mpl.rcParams['axes.titlesize'] = 18
    mpl.rcParams['axes.labelsize'] = 16
    mpl.rcParams['xtick.labelsize'] = 13
    mpl.rcParams['ytick.labelsize'] = 13
    mpl.rcParams['legend.fontsize'] = 13

    # Legend
    mpl.rcParams['legend.frameon'] = False
