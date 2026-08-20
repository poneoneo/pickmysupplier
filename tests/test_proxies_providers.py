"""Tests for the pure parts of proxies_providers.py — no network/browser calls.

The rest talks to the real ScrapingBee REST API and isn't unit-testable
without network access.
"""

from __future__ import annotations

import pytest

from sourcing_intel_cli.proxies_providers import (
	TARGET_COUNTRY,
	ScrapingBeeKeyError,
	_resolve_scrapingbee_key,
	_fetch_via_scrapingbee,
)


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

	def test_429_raises_key_error(self):
		# Quota exceeded on an otherwise-valid key.
		stub = _StubAPIRequest(_StubResponse(429))
		with pytest.raises(ScrapingBeeKeyError):
			_fetch_via_scrapingbee(stub, "https://endpoint.example", "my-key", "https://target.example")

	def test_401_raises_key_error(self):
		# Invalid/revoked/terminated key — a real case observed against the
		# live ScrapingBee API (distinct from 429's "valid key, no credits
		# left"), and previously fell through to the generic "not ok, skip
		# this page" path silently for every page, ending the scrape with
		# zero pages and no indication to the user that the key was the
		# problem.
		stub = _StubAPIRequest(_StubResponse(401))
		with pytest.raises(ScrapingBeeKeyError):
			_fetch_via_scrapingbee(stub, "https://endpoint.example", "my-key", "https://target.example")

	def test_other_failure_status_returns_response_not_ok(self):
		stub = _StubAPIRequest(_StubResponse(500))
		response = _fetch_via_scrapingbee(stub, "https://endpoint.example", "my-key", "https://target.example")
		assert response.ok is False

	def test_success_returns_response_text(self):
		stub = _StubAPIRequest(_StubResponse(200, "<html>ok</html>"))
		response = _fetch_via_scrapingbee(stub, "https://endpoint.example", "my-key", "https://target.example")
		assert response.ok is True
		assert response.text() == "<html>ok</html>"
