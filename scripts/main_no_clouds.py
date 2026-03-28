"""
Entry point for generating the no-cloud negative class dataset.

Usage:
    python scripts/main_no_clouds.py

Reads confirmed locations from cloud_gallery_full.csv (the full pipeline output).
Writes TARGET_ROWS clear-sky rows to no_clouds.csv.
Adjust TARGET_ROWS in no_clouds.py after inspecting per-class distribution in Part 3.
"""

import asyncio

from verycloudy.config import FILEPATH_CLOUDS_ALL_INFO_CLEAN_TESTSET, FILEPATH_NO_CLOUDS_TEST
from no_clouds import run

asyncio.run(run(FILEPATH_CLOUDS_ALL_INFO_CLEAN_TESTSET, FILEPATH_NO_CLOUDS_TEST))
