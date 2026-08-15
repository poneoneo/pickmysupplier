import os

from dotenv import load_dotenv

__version__ = "0.2.0"

load_dotenv(override=True)
BRIGHT_DATA_API_KEY: str = os.environ.get("BRIGHT_DATA_API_KEY", "")
SCRAPINGBEE_API_KEY: str = os.environ.get("SCRAPINGBEE_API_KEY", "")
GROQ_API_KEY: str = os.environ.get("GROQ_API_KEY", "")
LOGURU_LEVEL: str | None = os.environ.get("LOGURU_LEVEL")
