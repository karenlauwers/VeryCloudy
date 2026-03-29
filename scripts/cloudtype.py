"""
Task C — Extract cloud types and subtypes from title and tags columns.

Adds up to 3 primary cloud type columns (cloud_type1–3) and up to 2 subtype
columns (subtype1–2) to the input CSV, writing the result to a new file.

No API calls — pure text matching using word-boundary regex.
"""

import re
from pathlib import Path

import pandas as pd


# -------------------------
# Cloud type / subtype lists
# -------------------------

# Ordered longest-first so that e.g. "stratocumulus" is matched before "cumulus"
# and "cumulonimbus" is matched before "cumulus" / "nimbus".
CLOUD_TYPES = [
    "cumulonimbus",
    "stratocumulus",
    "nimbostratus",
    "cirrostratus",
    "cirrocumulus",
    "altocumulus",
    "altostratus",
    "cirrus",
    "stratus",
    "cumulus",
]

CLOUD_SUBTYPES = [
    "horseshoe vortex",   # multi-word first
    "cap cloud",
    "contrail",
    "fibrates",
    "fog",
    "undulatus",
    "virga",
    "volutus",
    "arcus",
    "radiatus",
    "cavum",
    "mamma",
    "tuba",
    "lacunosus",
    "lenticularis",
    "pileus",
    "noctilucent",
    "nacreous",
    "fluctus",
    "asperitas",
    "uncinus",
    "floccus",
    "castellanus",
    "distrail",
    "pyrocumulus",
    "congestus",
    "velum",
    "pannus",
    "fractus",
    "murus",
]

# Pre-compile patterns once: word-boundary, case-insensitive
_TYPE_PATTERNS = [(t, re.compile(rf"\b{re.escape(t)}\b", re.IGNORECASE)) for t in CLOUD_TYPES]
_SUBTYPE_PATTERNS = [(s, re.compile(rf"\b{re.escape(s)}\b", re.IGNORECASE)) for s in CLOUD_SUBTYPES]


# -------------------------
# Core matching helpers
# -------------------------

def _collect_matches(text: str, patterns: list[tuple[str, re.Pattern]]) -> list[str]:
    """Return all unique matches from text, ordered by position of first occurrence."""
    hits = []
    seen = set()
    for name, pat in patterns:
        m = pat.search(text)
        if m and name not in seen:
            hits.append((m.start(), name))
            seen.add(name)
    hits.sort(key=lambda x: x[0])
    return [name for _, name in hits]


def classify_row(title: str, tags: str) -> dict:
    """
    Extract up to 3 cloud types and 2 subtypes from title + tags.
    Title is checked first; tags second. Already-filled slots are never overwritten.
    Returns dict with keys cloud_type1, cloud_type2, cloud_type3, subtype1, subtype2.
    """
    title = title if isinstance(title, str) else ""
    tags = tags if isinstance(tags, str) else ""

    types: list[str] = []
    subtypes: list[str] = []

    for text in (title, tags):
        if len(types) < 3:
            for match in _collect_matches(text, _TYPE_PATTERNS):
                if match not in types:
                    types.append(match)
                if len(types) == 3:
                    break
        if len(subtypes) < 2:
            for match in _collect_matches(text, _SUBTYPE_PATTERNS):
                if match not in subtypes:
                    subtypes.append(match)
                if len(subtypes) == 2:
                    break

    def _slot(lst, i):
        return lst[i] if i < len(lst) else None

    return {
        "cloud_type1": _slot(types, 0),
        "cloud_type2": _slot(types, 1),
        "cloud_type3": _slot(types, 2),
        "subtype1":    _slot(subtypes, 0),
        "subtype2":    _slot(subtypes, 1),
    }


# -------------------------
# Pipeline
# -------------------------

def run(input_path: Path, out_csv: Path):
    if out_csv.exists():
        raise FileExistsError(
            f"Output file already exists: {out_csv}\n"
            "Create a new output path rather than overwriting."
        )

    df = pd.read_csv(input_path)

    results = df.apply(
        lambda r: classify_row(r.get("title", ""), r.get("tags", "")),
        axis=1,
        result_type="expand",
    )

    out_df = pd.concat([df, results], axis=1)
    out_df["is_cloudy"] = True
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(out_csv, index=False)

    filled_types = results["cloud_type1"].notna().sum()
    filled_subtypes = results["subtype1"].notna().sum()
    print(f"Done. {len(df)} rows → {out_csv}")
    print(f"  cloud_type1 filled: {filled_types} / {len(df)}")
    print(f"  subtype1 filled:    {filled_subtypes} / {len(df)}")
