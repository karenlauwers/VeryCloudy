"""
Entry point for Task B — historical weather enrichment.

Usage:
    python scripts/main_weather.py
"""

import asyncio
import os

from verycloudy.config import FILEPATH_CLOUDS_WITH_DATE_LOCATION_TESTSET, FILEPATH_WEATHER_TEST
from weather import run


def load_api_key() -> str:
    """
    Load OWM_API_KEY from environment.
    Prefer a project-root .env via find_dotenv(); fall back to OS env if not found.
    """
    try:
        from dotenv import load_dotenv, find_dotenv
        dotenv_file = find_dotenv(usecwd=False)
        if dotenv_file:
            load_dotenv(dotenv_file)
    except Exception:
        pass

    return os.environ.get("OWM_API_KEY", "")


async def main():
    api_key = load_api_key()
    if not api_key:
        raise RuntimeError(
            "OWM_API_KEY is missing.\n"
            "- Create a .env with:  OWM_API_KEY=YOUR_KEY  (recommended, at project root), OR\n"
            "- Set OWM_API_KEY in your OS/IDE environment."
        )
    await run(FILEPATH_CLOUDS_WITH_DATE_LOCATION_TESTSET, FILEPATH_WEATHER_TEST, api_key)


if __name__ == "__main__":
    asyncio.run(main())
