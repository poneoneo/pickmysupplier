"""This script is responsible for scraping data from the Alibaba website.
It uses the Playwright library to navigate through multiple pages
extract HTML content,and save it to disk. The script defines
functions to handle asynchronous tasks,interact with
browser contexts, and gather data from the scraped HTML files.
Additionally, it utilizes loguru for logging purposes and decouple for
managing environment variables.
"""

import asyncio
import os
import platform
import re
import urllib3

from loguru import logger
from playwright.async_api import async_playwright
from playwright.sync_api import Error as PError
from playwright.sync_api import sync_playwright
from rich import print as rprint
from rich.progress import Progress, SpinnerColumn

from . import BRIGHT_DATA_API_KEY, SCRAPINGBEE_API_KEY
from .html_to_disk import write_to_disk
from .proxies_utils import urls_pusher, goto_task, HTML_PAGE_RESULT

# Both providers are pinned to this ISO 3166-1 alpha-2 country for every
# request, so the target site always resolves the same currency (USD) from
# our exit IP's geolocation — see CLAUDE.md: prices used to come back in
# whatever currency the proxy's country uses (e.g. PLN from a Polish exit
# node), which `utils_scrapping.get_product_price` isn't guaranteed to parse.
TARGET_COUNTRY = "us"

_BD_CDP_URL_RE = re.compile(r"^(?P<scheme>\w+://)(?P<user>[^:@]+):(?P<password>[^@]+)@(?P<rest>.+)$")


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


class ScrapingBeeQuotaExceeded(RuntimeError):
	"""Raised when ScrapingBee reports the API key is out of credits (HTTP 429)."""


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
	:raises ScrapingBeeQuotaExceeded: If ScrapingBee reports HTTP 429
		(credits exhausted).
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
		raise ScrapingBeeQuotaExceeded(
			"La clé ScrapingBee a épuisé son quota de crédits (HTTP 429)."
		)
	return response


def _with_country_targeting(cdp_url: str, country: str = TARGET_COUNTRY) -> str:
	"""Insert BrightData's `-country-XX` flag into a Scraping Browser CDP URL.

	BrightData's Scraping Browser has no separate "country" request parameter
	— per-request geo-targeting is done by appending `-country-XX` to the
	username portion of the CDP WebSocket URL itself (see
	https://docs.brightdata.com/scraping-automation/scraping-browser/features/proxy-location),
	e.g. ``wss://brd-customer-...-zone-myzone:pass@brd.superproxy.io:9222``
	becomes ``wss://brd-customer-...-zone-myzone-country-us:pass@...``.

	:param cdp_url: The raw CDP WebSocket URL from `BRIGHT_DATA_API_KEY`.
	:type cdp_url: str
	:param country: Two-letter ISO country code to pin the exit node to.
	:type country: str
	:return: The URL with `-country-{country}` appended to the username, or
		the URL unchanged if it doesn't match the expected `scheme://user:pass@rest`
		shape (fails open rather than raising, so an unexpected credential
		format doesn't break scraping — it just won't be geo-pinned).
	:rtype: str
	"""
	match = _BD_CDP_URL_RE.match(cdp_url)
	if match is None:
		return cdp_url
	user = match.group("user")
	if re.search(r"-country-[a-z]{2}$", user):
		return cdp_url
	return (
		f"{match.group('scheme')}{user}-country-{country}:"
		f"{match.group('password')}@{match.group('rest')}"
	)


class BrightDataProxyProvider:
	BD_API_KEY = BRIGHT_DATA_API_KEY

	@classmethod
	@logger.catch()
	async def async_scraper(cls, *, save_in: str, key_words: str, page_results: int) -> None:
		"""
		Initiates scraping of Alibaba.com based on the provided keywords.

		:param save_in: The directory to store the raw HTML files.
		:type save_in: str
		:param key_words: The search term(s) for finding products on Alibaba. Enclose multiple keywords in quotes.
		:type key_words: str
		:param page_results: The number of pages to scrape. If omitted, 10 pages will be scraped.
		:type page_results: int

		:return: None
		:rtype: None

		:raises RuntimeError: If no internet connection is available, no API key is set, the
			BrightData account is suspended, or another unexpected connection error occurs.

		:raises playwright._impl._errors.Error: If there is an error with the playwright browser.

		:raises Exception: If there is an error processing a page.
		"""
		if cls.BD_API_KEY == "":
			rprint("[red]You need to set your  API key to use BrightData proxies ... [/red]")
			raise RuntimeError("You need to set your BrightData API key to use BrightData proxies.")
		with Progress(
			SpinnerColumn(finished_text="[bold green]finished ✓[/bold green]"),
			*Progress.get_default_columns(),
			transient=True,
		) as progress:
			async with async_playwright() as p:
				logger.info("Connecting to CDP and creating the browser... ")
				try:
					browser = await p.chromium.connect_over_cdp(_with_country_targeting(cls.BD_API_KEY))
				except urllib3.exceptions.NameResolutionError:
					rprint("[red]check your internet connection")
					raise RuntimeError("Check your internet connection.")
				except Exception as e:
					if "Account is suspended" in str(e):
						rprint(
							"[red]Bright data account has been suspended by system may your api is exhausted recharge it and try again. You can use `--sync-api` flag after your last command to enable sync scrapping but you may not encounter enought success.  [/red]"
						)
						raise RuntimeError("BrightData account has been suspended.") from e
					elif "Executable doesn't exist at" in str(e):
						rprint(
							"[white]Seems like playwright is not installed or needs to be update. We will install it for you after that rerun your previous command [/white]"
						)
						os.system("playwright install")
						if platform.system() == "Windows":
							os.system("cls")
						if platform.system() == "Linux":
							os.system("clear")
						raise RuntimeError(
							"Playwright browsers were not installed; they have been installed now, please retry."
						) from e
					elif "WebSocket error" in str(e):
						rprint(
							"[red]Web Socket is disconnected. You May need to activate your Internet connexion"
						)
						raise RuntimeError("WebSocket is disconnected. Check your internet connection.") from e
					elif "try connecting via ws" in str(e):
						rprint(
							"[red] You must to set a SCRAPING BROWSER API key (e.g 'ws://127.0.0.1:3000') to enable connection via websocket. "
						)
						raise RuntimeError(
							"You must set a SCRAPING BROWSER API key (e.g. 'ws://127.0.0.1:3000') to enable connection via websocket."
						) from e
					else:
						rprint(f"[red]Unexpected error occured : \n{e}")
						raise RuntimeError(f"Unexpected error occured: {e}") from e

				context_browser = await browser.new_context()
				s_one = asyncio.Semaphore(value=10)
				logger.info("Loading pages results ... ")
				async with asyncio.Lock():
					async with asyncio.TaskGroup() as tg:
						task = progress.add_task("[green blink] async Scraping...", start=False)
						for url in urls_pusher(words=key_words, stop_at=page_results):
							async with asyncio.Lock():
								page = await context_browser.new_page()
							tg.create_task(
								goto_task(
									url=url,
									semaphore=s_one,
									progress=progress,
									task=task,
									tg_instance=tg,
									context_browser=context_browser,
									page=page,
									page_results=page_results,
								)
							)
				write_to_disk(save_in, HTML_PAGE_RESULT)

	@classmethod
	def sync_scraper(cls, *, save_in: str, key_words: str, page_results: int) -> None:
		"""
		Initiates synchronous scraping of Alibaba.com based on the provided keywords.

		:param save_in: The directory to store the raw HTML files.
		:type save_in: str
		:param key_words: The search term(s) for finding products on Alibaba.
		:type key_words: str
		:param page_results: The number of pages to scrape.
		:type page_results: int
		:return: None
		:rtype: None
		:raises RuntimeError: If no API key is set, playwright isn't installed, or another
			unexpected connection error occurs.
		"""
		if cls.BD_API_KEY == "":
			rprint("[red]You need to set your  API key to use BrightData proxies ... [/red]")
			raise RuntimeError("You need to set your BrightData API key to use BrightData proxies.")
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
			try:
				browser = playwright.chromium.connect_over_cdp(_with_country_targeting(cls.BD_API_KEY))
			except PError as e:
				if "exists" in e.message:
					rprint(
						"[white] Seems like playwright is not installed or need to be update. lets sic install it for you... [/white]"
					)
					os.system("playwright install")
					raise RuntimeError(
						"Playwright browsers were not installed; they have been installed now, please retry."
					) from e
				elif "try connecting via ws" in e.message:
					rprint(
						"[red] You must to set a SCRAPING BROWSER API key (e.g 'ws://127.0.0.1:3000') to enable connection via websocket. "
					)
					raise RuntimeError(
						"You must set a SCRAPING BROWSER API key (e.g. 'ws://127.0.0.1:3000') to enable connection via websocket."
					) from e
				else:
					rprint(f"[red]Unexpected error occured : \n{e}")
					raise RuntimeError(f"Unexpected error occured: {e}") from e
			context = browser.new_context()
			for url in urls_pusher(words=key_words, stop_at=page_results):
				logger.info(f"Loading page {url.split('page=')[1]} ... ")
				page = context.new_page()
				try:
					response = page.goto(url, wait_until="domcontentloaded", timeout=0)
					if response is None:
						logger.warning(f"No response for page {url.split('page=')[1]}, skipping it.")
						page.close()
						continue
					logger.info(
						f"Returns the text representation of response body from page {url.split('page=')[1]} ... "
					)
					html_content = response.text()
					progress.start_task(task)
					progress.update(task, advance=100 / page_results)
					global HTML_PAGE_RESULT
					HTML_PAGE_RESULT.append(html_content)
					logger.info(f"Closing the page {url.split('page=')[1]} ... ")
					page.close()
				except PError as e:
					if "ERR_INTERNET_DISCONNECTED" in e.message:
						raise RuntimeError("Check your internet connection ... ") from e
			write_to_disk(save_in, HTML_PAGE_RESULT)


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
		:raises ScrapingBeeQuotaExceeded: If ScrapingBee reports the resolved
			key is out of credits (HTTP 429) — callers should catch this
			before the generic `RuntimeError` to show a specific "get your
			own free key" message.
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
				for url in urls_pusher(words=key_words, stop_at=page_results):
					logger.info(f"Loading page {url.split('page=')[1]} ... ")
					response = _fetch_via_scrapingbee(api_request, cls.ENDPOINT, resolved_key, url)
					if not response.ok:
						logger.warning(
							f"ScrapingBee request failed for page {url.split('page=')[1]} "
							f"(status {response.status}), skipping it."
						)
						continue
					logger.info(
						f"Returns the text representation of response body from page {url.split('page=')[1]} ... "
					)
					progress.start_task(task)
					html_content = response.text()
					progress.update(task, advance=100 / page_results)
					global HTML_PAGE_RESULT
					HTML_PAGE_RESULT.append(html_content)
					logger.info(f"Closing the page {url.split('page=')[1]} ... ")
			finally:
				api_request.dispose()
				playwright.stop()
		write_to_disk(save_in, HTML_PAGE_RESULT)
