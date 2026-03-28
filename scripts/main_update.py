"""
Entry point for post-processing fixes.

Usage:
    python scripts/main_update.py
"""

from verycloudy.config import (
    FILEPATH_CLOUDS_WITH_DATE_LOC_WEATHER_TYPE_TESTSET,
    FILEPATH_CLOUDS_ALL_INFO_CLEAN_TESTSET,
)
from update import run

run(
    FILEPATH_CLOUDS_WITH_DATE_LOC_WEATHER_TYPE_TESTSET,
    FILEPATH_CLOUDS_ALL_INFO_CLEAN_TESTSET,
)
