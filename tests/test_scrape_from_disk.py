"""Tests for PageParser against a hand-built HTML fixture.

The fixture (tests/fixtures/scraped_pages_sample/) is synthetic, not real
scraped marketplace content — this project deliberately avoids committing or
redistributing scraped pages (see CLAUDE.md's notes on scraping ToS risk).
It reproduces the real page's JSON schema (window.__page__data_sse*._offer_list,
a `.fy26-product-card` div for supplier verification) closely enough to
exercise the whole disk -> JSON -> dict parsing pipeline without any network
access.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sourcing_intel_cli.scrape_from_disk import PageParser

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "scraped_pages_sample"


@pytest.fixture
def parser():
	return PageParser(targeted_folder=FIXTURES_DIR)


class TestDetectedSuppliers:
	def test_identical_supplier_across_pages_is_deduped(self, parser):
		suppliers = parser.detected_suppliers()
		assert len(suppliers) == 1

	def test_supplier_fields_are_parsed_correctly(self, parser):
		supplier = parser.detected_suppliers()[0]
		assert supplier["name"] == "shenzhen acme co."
		assert supplier["verified_type"] == "gold"
		assert supplier["sopi_level"] == 4
		assert supplier["country_name"] == "chine"
		assert supplier["gold_supplier_year"] == "5"
		assert supplier["supplier_service_score"] == 4.7


class TestDetectedProducts:
	def test_returns_one_product_per_distinct_offer(self, parser):
		products = parser.detected_products()
		assert len(products) == 2

	def test_product_fields_are_parsed_correctly(self, parser):
		products = {p["name"]: p for p in parser.detected_products()}
		pro_x = products["wireless earbuds pro x"]
		assert pro_x["min_price"] == 3.20
		assert pro_x["max_price"] == 5.80
		assert pro_x["minimum_to_order"] == 100.0
		assert pro_x["ordered_or_sold"] == 1250.0
		assert pro_x["certifications"] == "CE"
		assert pro_x["supplied_by"] == "shenzhen acme co."

	def test_missing_certifications_default_to_empty_string(self, parser):
		products = {p["name"]: p for p in parser.detected_products()}
		lite = products["wireless earbuds lite"]
		assert lite["certifications"] == ""


def test_missing_folder_raises_type_error():
	# _html_files_explorer is decorated with @logger.catch(FileNotFoundError),
	# whose default reraise=False swallows the exception and returns None
	# instead of propagating it — despite the method's own docstring claiming
	# `:raises FileNotFoundError:`. The FileNotFoundError never surfaces;
	# iterating over the swallowed None blows up with a TypeError instead.
	parser = PageParser(targeted_folder="does/not/exist")
	with pytest.raises(TypeError):
		parser.detected_suppliers()
