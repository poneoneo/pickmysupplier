"""Tests for the pure parts of proxies_providers.py — no network/browser calls.

`_with_country_targeting` is the only piece of this module that's plain string
logic; the rest talks to real proxy providers (BrightData CDP, ScrapingBee
REST) and isn't unit-testable without network access.
"""

from __future__ import annotations

import pytest

from sourcing_intel_cli.proxies_providers import (
	TARGET_COUNTRY,
	ScrapingBeeQuotaExceeded,
	_with_country_targeting,
	_resolve_scrapingbee_key,
	_fetch_via_scrapingbee,
)


class TestWithCountryTargeting:
	def test_inserts_country_flag_before_password(self):
		url = "wss://brd-customer-abc-zone-myzone:secretpass@brd.superproxy.io:9222"
		assert _with_country_targeting(url, "us") == (
			"wss://brd-customer-abc-zone-myzone-country-us:secretpass@brd.superproxy.io:9222"
		)

	def test_uses_a_different_country_code(self):
		url = "wss://user:pass@brd.superproxy.io:9222"
		assert _with_country_targeting(url, "de") == "wss://user-country-de:pass@brd.superproxy.io:9222"

	def test_does_not_double_up_if_already_targeted(self):
		url = "wss://user-country-us:pass@brd.superproxy.io:9222"
		assert _with_country_targeting(url, "us") == url

	def test_leaves_unrecognized_format_unchanged(self):
		# fails open rather than raising, so an unexpected credential shape
		# doesn't break scraping — just skips geo-pinning for that call.
		url = "ws://127.0.0.1:3000"
		assert _with_country_targeting(url, "us") == url

	def test_empty_string_is_left_unchanged(self):
		assert _with_country_targeting("", "us") == ""


class TestResolveScrapingbeeKey:
	def test_uses_visitor_key_when_provided(self):
		assert _resolve_scrapingbee_key("visitor-key", "owner-key") == "visitor-key"

	def test_falls_back_to_owner_key_when_visitor_key_is_none(self):
		assert _resolve_scrapingbee_key(None, "owner-key") == "owner-key"

	def test_falls_back_to_owner_key_when_visitor_key_is_empty_string(self):
		assert _resolve_scrapingbee_key("", "owner-key") == "owner-key"


class _StubResponse:
	def __init__(self, status: int, text: str = ""):
		self.status = status
		self.ok = status < 400
		self._text = text

	def text(self):
		return self._text


class _StubAPIRequest:
	def __init__(self, response: _StubResponse):
		self._response = response
		self.last_params = None

	def get(self, url, params=None, timeout=None):
		self.last_params = params
		return self._response


class TestFetchViaScrapingbee:
	def test_uses_provided_api_key(self):
		stub = _StubAPIRequest(_StubResponse(200, "<html></html>"))
		_fetch_via_scrapingbee(stub, "https://endpoint.example", "my-key", "https://target.example")
		assert stub.last_params["api_key"] == "my-key"

	def test_pins_country_and_premium_proxy(self):
		stub = _StubAPIRequest(_StubResponse(200))
		_fetch_via_scrapingbee(stub, "https://endpoint.example", "my-key", "https://target.example")
		assert stub.last_params["country_code"] == TARGET_COUNTRY
		assert stub.last_params["premium_proxy"] == "true"

	def test_429_raises_quota_exceeded(self):
		stub = _StubAPIRequest(_StubResponse(429))
		with pytest.raises(ScrapingBeeQuotaExceeded):
			_fetch_via_scrapingbee(stub, "https://endpoint.example", "my-key", "https://target.example")

	def test_non_429_failure_returns_response_not_ok(self):
		stub = _StubAPIRequest(_StubResponse(500))
		response = _fetch_via_scrapingbee(stub, "https://endpoint.example", "my-key", "https://target.example")
		assert response.ok is False

	def test_success_returns_response_text(self):
		stub = _StubAPIRequest(_StubResponse(200, "<html>ok</html>"))
		response = _fetch_via_scrapingbee(stub, "https://endpoint.example", "my-key", "https://target.example")
		assert response.ok is True
		assert response.text() == "<html>ok</html>"
