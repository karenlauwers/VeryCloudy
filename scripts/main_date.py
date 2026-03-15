from verycloudy.config import FILEPATH_CLOUDS_CSV, FILEPATH_DATE_CSV
import asyncio
from date import run  

if __name__ == "__main__":
    asyncio.run(run(FILEPATH_CLOUDS_CSV, FILEPATH_DATE_CSV))