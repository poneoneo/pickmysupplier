"""Tests for the pure parts of proxies_providers.py — no network/browser calls.

`_with_country_targeting` is the only piece of this module that's plain string
logic; the rest talks to real proxy providers (BrightData CDP, ScrapingBee
REST) and isn't unit-testable without network access.
"""

from __future__ import annotations

from sourcing_intel_cli.proxies_providers import _with_country_targeting


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
