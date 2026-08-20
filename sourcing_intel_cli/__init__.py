import os
import sys

from dotenv import load_dotenv
from loguru import logger

__version__ = "0.2.0"

load_dotenv(override=True)
SCRAPINGBEE_API_KEY: str = os.environ.get("SCRAPINGBEE_API_KEY", "")
GROQ_API_KEY: str = os.environ.get("GROQ_API_KEY", "")
LOGURU_LEVEL: str | None = os.environ.get("LOGURU_LEVEL")

# Hosted platforms like Streamlit Community Cloud have no `.env` file —
# secrets are set through the platform's own UI instead and only reach the
# app via `st.secrets`, not `os.environ`. Fall back to that here (import
# guarded: this module loads outside a real Streamlit run too, e.g. in
# tests, where `st.secrets` would otherwise raise) so the rest of the
# codebase can keep reading these two module-level constants unchanged
# regardless of where the app is running.
if not SCRAPINGBEE_API_KEY or not GROQ_API_KEY:
	try:
		import streamlit as st

		SCRAPINGBEE_API_KEY = SCRAPINGBEE_API_KEY or st.secrets.get("SCRAPINGBEE_API_KEY", "")
		GROQ_API_KEY = GROQ_API_KEY or st.secrets.get("GROQ_API_KEY", "")
	except Exception:
		pass

# loguru auto-creates a default stderr handler (id 0) with diagnose=True,
# which prints local variable values from the traceback's stack frames —
# including a visitor's ScrapingBee API key, if it's a local variable on any
# frame the exception passed through when `logger.exception(...)` is called.
# Remove it and re-add an equivalent stderr sink with diagnose=False, closing
# the same leak for the console that the file sink below closes for the file.
logger.remove()
logger.add(sys.stderr, level=LOGURU_LEVEL or "INFO", diagnose=False)

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
