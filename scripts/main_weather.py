"""
Entry point for Task B — historical weather enrichment.

Usage:
    python scripts/main_weather.py
"""

import asyncio

from verycloudy.config import FILEPATH_CLOUDS_WITH_DATE_LOC, FILEPATH_WEATHER
from weather import run


async def main():
    await run(FILEPATH_CLOUDS_WITH_DATE_LOC, FILEPATH_WEATHER)


if __name__ == "__main__":
    asyncio.run(main())
