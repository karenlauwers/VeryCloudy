"""
Entry point for Task B — historical weather enrichment.

Usage:
    python scripts/main_weather.py
"""

import asyncio

from verycloudy.config import FILEPATH_CLOUDS_WITH_DATE_LOCATION_TESTSET, FILEPATH_WEATHER_TEST_V3
from weather import run


async def main():
    await run(FILEPATH_CLOUDS_WITH_DATE_LOCATION_TESTSET, FILEPATH_WEATHER_TEST_V3)


if __name__ == "__main__":
    asyncio.run(main())
