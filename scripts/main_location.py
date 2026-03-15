# import asyncio
# import os

# from verycloudy.config import FILEPATH_CLOUDS_WITH_DATE_TESTSET, FILEPATH_LOCATION_TEST
# from location import run


# api_key = os.environ.get("OWM_API_KEY", "")
# asyncio.run(run(FILEPATH_CLOUDS_WITH_DATE_TESTSET, FILEPATH_LOCATION_TEST, api_key))

from pathlib import Path
import asyncio
import os

from verycloudy.config import FILEPATH_CLOUDS_WITH_DATE_TESTSET, FILEPATH_LOCATION_TEST
from location import run


def load_api_key() -> str:
    """
    Load OWM_API_KEY from environment.
    Prefer a project-root .env via find_dotenv(); fall back to OS env if not found.
    """
    try:
        from dotenv import load_dotenv, find_dotenv  # optional dependency
        # Search from this file's folder upward for the nearest .env
        dotenv_file = find_dotenv(usecwd=False)
        if dotenv_file:
            load_dotenv(dotenv_file)
    except Exception:
        # If python-dotenv isn't installed or any error occurs,
        # we'll just rely on the existing OS environment.
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
    await run(FILEPATH_CLOUDS_WITH_DATE_TESTSET, FILEPATH_LOCATION_TEST, api_key)


if __name__ == "__main__":
    asyncio.run(main())