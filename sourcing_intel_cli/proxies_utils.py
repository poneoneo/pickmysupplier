from urllib.parse import urlencode

# The site's product search API (JSON). Since 2026-11 the HTML results page
# no longer embeds its offers JSON and is behind a captcha for anything but
# ScrapingBee's stealth proxy (75 credits/page); this API answers the plain
# premium proxy without JS rendering (10 credits/page) and is the only
# source left with product/shipping/supplier-service scores and
# certification names. Measured with real calls on 2026-11-18.
SEARCH_API_URL = "https://www.alibaba.com/search/api/proTextSearch"
PAGE_SIZE = 40


def urls_pusher(words: str, stop_at: int):
	"""Yield one product search API URL per results page.

	:param words: The search keywords.
	:type words: str
	:param stop_at: The number of pages to fetch (1 to `stop_at`).
	:type stop_at: int
	:return: A generator of URLs, `page=` last so `url.split("page=")[1]` is
		the page number (used in log messages).
	:rtype: Iterator[str]
	"""
	for i in range(1, stop_at + 1):
		# currency=USD: without it, prices come back in the proxy exit
		# node's currency (EUR, GBP... — measured), even with the US pin.
		query = urlencode(
			{"query": words, "pageSize": PAGE_SIZE, "langident": "en", "currency": "USD", "page": i}
		)
		yield f"{SEARCH_API_URL}?{query}"
