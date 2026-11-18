"""This script is responsible for scraping data from the Alibaba website.
It uses the Playwright library to navigate through multiple pages
extract HTML content,and save it to disk. The script defines
functions to handle asynchronous tasks,interact with
browser contexts, and gather data from the scraped HTML files.
Additionally, it utilizes loguru for logging purposes and decouple for
managing environment variables.
"""

import re

from loguru import logger
from playwright.sync_api import sync_playwright
from rich import print as rprint
from rich.progress import Progress, SpinnerColumn

from . import SCRAPINGBEE_API_KEY
from .html_to_disk import write_to_disk
from .proxies_utils import urls_pusher

# Pinned to this ISO 3166-1 alpha-2 country for every request, so the target
# site always resolves the same currency (USD) from our exit IP's
# geolocation — see CLAUDE.md: prices used to come back in whatever currency
# the proxy's country uses (e.g. PLN from a Polish exit node), which
# `utils_scrapping.get_product_price` isn't guaranteed to parse.
TARGET_COUNTRY = "us"


def _resolve_scrapingbee_key(visitor_key: str | None, fallback_key: str) -> str:
	"""Pick which ScrapingBee API key to use for a scrape.

	:param visitor_key: The key a visitor typed into the Scraper page's
		optional field, if any.
	:type visitor_key: str | None
	:param fallback_key: The owner's key from `.env` (`SCRAPINGBEE_API_KEY`).
	:type fallback_key: str
	:return: `visitor_key` if non-empty, else `fallback_key`.
	:rtype: str
	"""
	return visitor_key or fallback_key


class ScrapingBeeKeyError(RuntimeError):
	"""Raised when ScrapingBee reports the API key can't be used right now.

	Covers both an exhausted quota and an invalid, revoked, or expired key.
	Without catching 401 too, a revoked/terminated key used to fail
	silently, one page at a time, via the generic "not ok, skip this page"
	path — ending the scrape with zero pages and no indication to the user
	that the key was the actual problem.

	:param message: Human-readable description, for the logs.
	:type message: str
	:param reason: `"quota"` (valid key, out of credits) or `"invalid"`
		(invalid, revoked, or expired key) — lets the UI tell the visitor
		which one it is instead of a vague "out of credits or invalid".
	:type reason: str
	"""

	def __init__(self, message: str, reason: str):
		super().__init__(message)
		self.reason = reason


class TargetSiteBlockedError(RuntimeError):
	"""Raised when the target site answered with a captcha page instead of results.

	ScrapingBee still returns HTTP 200 for it and bills it like a real page
	(25 credits with premium proxy + JS rendering, measured 2026-11-18), so
	the scrape stops at the first one rather than paying for every
	remaining page only to get the same captcha back.
	"""


# Markers of the target site's anti-bot "punish" page, taken from a real
# captcha response (title "Captcha Interception", assets and redirect under
# a `_____tmd_____/punish` path).
_CAPTCHA_TITLE = re.compile(r"<title>[^<]*captcha[^<]*</title>", re.IGNORECASE)
_PUNISH_PATH = "_____tmd_____/punish"
# What ScrapingBee's 401 body says when the key is fine but its monthly
# call quota is used up (observed: "Monthly API calls limit reached: 1000").
_QUOTA_REACHED = re.compile(r"limit reached", re.IGNORECASE)


def is_blocked_page(html: str) -> bool:
	"""Whether `html` is the target site's captcha page rather than search results.

	:param html: The page HTML as returned by ScrapingBee.
	:type html: str
	:return: True if the page is a captcha/anti-bot interception page.
	:rtype: bool
	"""
	return bool(_CAPTCHA_TITLE.search(html)) or _PUNISH_PATH in html


def _fetch_via_scrapingbee(api_request, endpoint: str, api_key: str, url: str):
	"""Fetch one page's HTML through the ScrapingBee REST API.

	Isolated from `ScrapingBeeProxyProvider.sync_scraper`'s Playwright
	setup/teardown so the api_key-resolution and quota-detection logic can
	be unit tested with a stubbed `api_request` (see
	`tests/test_proxies_providers.py`) instead of needing a real browser or
	network access.

	:param api_request: A Playwright `APIRequestContext` (or a stub exposing
		the same `.get(url, params=..., timeout=...)` -> response interface).
	:param endpoint: The ScrapingBee REST endpoint.
	:type endpoint: str
	:param api_key: The resolved ScrapingBee API key (visitor's own, or the
		owner's `.env` fallback — see `_resolve_scrapingbee_key`).
	:type api_key: str
	:param url: The target page URL to scrape.
	:type url: str
	:raises ScrapingBeeKeyError: If ScrapingBee reports HTTP 429 or a 401
		whose body says the monthly limit is reached (`reason="quota"`), or
		any other HTTP 401 (`reason="invalid"`).
	:return: The response object (`.ok`, `.status`, `.text()`).
	"""
	response = api_request.get(
		endpoint,
		params={
			"api_key": api_key,
			"url": url,
			"render_js": "true",
			"premium_proxy": "true",
			"country_code": TARGET_COUNTRY,
		},
		timeout=0,
	)
	if response.status == 429:
		raise ScrapingBeeKeyError(
			"The ScrapingBee key has run out of credits (HTTP 429).", reason="quota"
		)
	if response.status == 401:
		# ScrapingBee also uses 401 for an exhausted quota, not only for a
		# bad key — tell them apart by the body, or a visitor who simply
		# used up their credits is told their key is invalid.
		body = response.text()
		if _QUOTA_REACHED.search(body):
			raise ScrapingBeeKeyError(
				f"The ScrapingBee key has run out of credits (HTTP 401: {body[:200]}).",
				reason="quota",
			)
		raise ScrapingBeeKeyError(
			"The ScrapingBee key is invalid, expired, or revoked (HTTP 401).", reason="invalid"
		)
	return response


def _collect_html_pages(
	api_request,
	endpoint: str,
	api_key: str,
	key_words: str,
	page_results: int,
	progress,
	task,
) -> list[str]:
	"""Fetch every result page's HTML into a list local to this call.

	A local list instead of the old module-global `HTML_PAGE_RESULT` — two
	scrapes running at once (two different site visitors) used to share
	and clobber the same global list; each call now gets its own.

	:param api_request: A Playwright `APIRequestContext` (or a stub, see
		`tests/test_proxies_providers.py`).
	:param endpoint: The ScrapingBee REST endpoint.
	:type endpoint: str
	:param api_key: The resolved ScrapingBee API key.
	:type api_key: str
	:param key_words: The search term(s) for finding products.
	:type key_words: str
	:param page_results: The number of pages to scrape.
	:type page_results: int
	:param progress: The `rich.progress.Progress` bar to advance as pages complete.
	:param task: The `Progress` task id returned by `progress.add_task`.
	:raises TargetSiteBlockedError: As soon as one page comes back as the
		target site's captcha page — no further page is requested.
	:return: The HTML content of every page that responded OK, in order.
	:rtype: list[str]
	"""
	html_pages: list[str] = []
	for url in urls_pusher(words=key_words, stop_at=page_results):
		logger.info(f"Loading page {url.split('page=')[1]} ... ")
		response = _fetch_via_scrapingbee(api_request, endpoint, api_key, url)
		if not response.ok:
			logger.warning(
				f"ScrapingBee request failed for page {url.split('page=')[1]} "
				f"(status {response.status}), skipping it."
			)
			continue
		logger.info(
			f"Returns the text representation of response body from page {url.split('page=')[1]} ... "
		)
		html = response.text()
		if is_blocked_page(html):
			raise TargetSiteBlockedError(
				f"The target site answered page {url.split('page=')[1]} with a captcha; "
				"stopping before spending credits on the remaining pages."
			)
		progress.start_task(task)
		html_pages.append(html)
		progress.update(task, advance=100 / page_results)
		logger.info(f"Closing the page {url.split('page=')[1]} ... ")
	return html_pages


class ScrapingBeeProxyProvider:
	SB_API_KEY = SCRAPINGBEE_API_KEY
	ENDPOINT = "https://app.scrapingbee.com/api/v1/"

	@classmethod
	def sync_scraper(
		cls, *, save_in: str, key_words: str, page_results: int, api_key: str | None = None
	) -> None:
		"""
		Initiates synchronous scraping via the ScrapingBee API based on the provided keywords.

		ScrapingBee renders the target page server-side (JS execution included) and returns
		the resulting HTML in the response body, so no local browser navigation is needed —
		Playwright's request context is used purely as an HTTP client.

		:param save_in: The directory to store the raw HTML files.
		:type save_in: str
		:param key_words: The search term(s) for finding products on Alibaba.
		:type key_words: str
		:param page_results: The number of pages to scrape.
		:type page_results: int
		:param api_key: A visitor-supplied ScrapingBee key to use instead of the
			owner's `SCRAPINGBEE_API_KEY` from `.env`, if provided.
		:type api_key: str | None
		:return: None
		:rtype: None
		:raises RuntimeError: If no API key is set (neither `api_key` nor the
			owner's `.env` key).
		:raises ScrapingBeeKeyError: If ScrapingBee reports the resolved key
			is out of credits (HTTP 429) or invalid/revoked/expired (HTTP
			401) — callers should catch this before the generic
			`RuntimeError` to show a specific "your key isn't working"
			message rather than a generic scraping-failed one.
		:raises TargetSiteBlockedError: If the target site answers with a
			captcha page — also to be caught before `RuntimeError`.
		"""
		resolved_key = _resolve_scrapingbee_key(api_key, cls.SB_API_KEY)
		if resolved_key == "":
			rprint("[red]You need to set your  API key to use ScrapingBee proxies ... [/red]")
			raise RuntimeError("You need to set your ScrapingBee API key to use ScrapingBee proxies.")
		with Progress(
			SpinnerColumn(finished_text="[bold green]finished ✓[/bold green]"),
			*Progress.get_default_columns(),
			transient=True,
		) as progress:
			task = progress.add_task(
				"[green blink] Sync Scraping...",
				start=False,
			)
			playwright = sync_playwright().start()
			api_request = playwright.request.new_context()
			try:
				html_pages = _collect_html_pages(
					api_request, cls.ENDPOINT, resolved_key, key_words, page_results, progress, task
				)
			finally:
				api_request.dispose()
				playwright.stop()
		write_to_disk(save_in, html_pages)
