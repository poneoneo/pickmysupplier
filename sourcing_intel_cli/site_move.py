"""Validation of the "site has moved" target URL.

The project moved from Streamlit Community Cloud (sleeps when idle, no
custom domain) to its own VPS. The old `*.streamlit.app` address is kept
alive because it's already on the author's CV, but only to send visitors to
the new domain: when the `MOVED_TO_URL` setting is present (in practice,
only in the Streamlit Cloud secrets), `app.py` shows a "site has moved" page
instead of the app.

The value ends up inside a link and a `<script>`, so it is validated here
rather than trusted as-is, even though it comes from our own secrets.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

# Conservative allow-list: no quotes, angle brackets, spaces or backslashes
# — nothing that could break out of an HTML attribute or a JS string.
_SAFE_URL_CHARS = re.compile(r"^[A-Za-z0-9\-._~:/?#\[\]@!$&()*+,;=%]+$")


def normalize_moved_to_url(value: str | None) -> str | None:
	"""Return a safe, normalized HTTPS URL to redirect to, or None.

	:param value: Raw setting value (from an env var or `st.secrets`), or
		None when the setting is absent.
	:type value: str | None
	:return: The URL without surrounding whitespace or trailing slash, or
		`None` when the setting is unset or not a plain `https://` URL with
		a host — an invalid value disables the move page rather than
		producing a broken or unsafe link.
	:rtype: str | None
	"""
	if value is None:
		return None
	url = value.strip().rstrip("/")
	if not url or not _SAFE_URL_CHARS.match(url):
		return None
	parts = urlsplit(url)
	if parts.scheme != "https" or not parts.hostname:
		return None
	return url
