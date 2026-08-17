import os

from dotenv import load_dotenv
from loguru import logger

__version__ = "0.2.0"

load_dotenv(override=True)
BRIGHT_DATA_API_KEY: str = os.environ.get("BRIGHT_DATA_API_KEY", "")
SCRAPINGBEE_API_KEY: str = os.environ.get("SCRAPINGBEE_API_KEY", "")
GROQ_API_KEY: str = os.environ.get("GROQ_API_KEY", "")
LOGURU_LEVEL: str | None = os.environ.get("LOGURU_LEVEL")

# File sink so errors survive past the terminal that launched Streamlit —
# app.py's uncaught-exception paths now show a friendly message on the page
# (see .streamlit/config.toml's showErrorDetails) instead of a traceback, so
# this file is the actual place to look up what failed. diagnose=False keeps
# local variable values (which can include API keys) out of the log file.
#
# Deliberately hardcoded to INFO rather than `LOGURU_LEVEL` (typically
# "CRITICAL" in .env, meant to keep the terminal quiet): a level that
# silences the console shouldn't also silence the one file meant to capture
# enough context to debug a reported problem after the fact.
logger.add(
	"logs/app.log",
	level="INFO",
	rotation="10 MB",
	retention="14 days",
	encoding="utf-8",
	backtrace=True,
	diagnose=False,
)
