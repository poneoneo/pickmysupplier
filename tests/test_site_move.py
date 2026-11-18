"""Tests for site_move.py — validating the "site has moved" target URL.

The old Streamlit Community Cloud deployment stays online (it's on the
user's CV) but only points visitors to the new domain; the target comes
from a secret, so it is validated before being put in a link or script.
"""

from __future__ import annotations

from sourcing_intel_cli.site_move import normalize_moved_to_url


class TestNormalizeMovedToUrl:
	def test_unset_means_no_move(self):
		assert normalize_moved_to_url(None) is None
		assert normalize_moved_to_url("") is None
		assert normalize_moved_to_url("   ") is None

	def test_accepts_plain_https_url(self):
		assert normalize_moved_to_url("https://pickmysupplier.com") == "https://pickmysupplier.com"

	def test_strips_whitespace_and_trailing_slash(self):
		assert normalize_moved_to_url("  https://pickmysupplier.com/  ") == "https://pickmysupplier.com"

	def test_rejects_non_https_schemes(self):
		# A typo or a tampered secret must never turn into a javascript:
		# link or a downgrade to plain http on the moved page.
		assert normalize_moved_to_url("http://pickmysupplier.com") is None
		assert normalize_moved_to_url("javascript:alert(1)") is None
		assert normalize_moved_to_url("pickmysupplier.com") is None

	def test_rejects_urls_with_characters_that_could_break_out_of_html_or_js(self):
		assert normalize_moved_to_url('https://pickmysupplier.com/"><script>') is None
		assert normalize_moved_to_url("https://pickmysupplier.com/'x") is None
		assert normalize_moved_to_url("https://pick mysupplier.com") is None

	def test_rejects_urls_without_a_host(self):
		assert normalize_moved_to_url("https://") is None
		assert normalize_moved_to_url("https:///path") is None
