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


class TestAppenderResilience:
	"""A single malformed offer must be skipped, not take down the whole batch."""

	def _good_product_offer(self):
		return {
			"companyName": "Shenzhen Acme Co.",
			"title": "<span> </span>Wireless Earbuds Pro X",
			"price": "$3.20-$5.80",
			"moq": "Min. order: 100 pieces",
			"soldOrder": "1,250 sold",
			"productScore": 4.8,
			"reviewCount": 320,
			"reviewScore": 4.9,
			"shippingScore": 4.6,
			"certifications": [{"prefixIcons": [{"name": "CE"}]}],
		}

	def _good_supplier_offer(self):
		return {
			"companyName": "Shenzhen Acme Co.",
			"displayStarLevel": 4,
			"countryCode": "CN",
			"goldSupplierYears": "5 Years",
			"supplierServiceScore": 4.7,
		}

	def test_one_malformed_product_offer_is_skipped_not_fatal(self, parser):
		bad_offer = self._good_product_offer() | {"title": "broken"}
		del bad_offer["moq"]  # triggers a KeyError inside the dict comprehension
		good_offer = self._good_product_offer()

		products = parser._produtcs_appender(offers_list=[bad_offer, good_offer], products=[])

		assert len(products) == 1
		assert products[0]["name"] == "wireless earbuds pro x"

	def test_one_malformed_supplier_offer_is_skipped_not_fatal(self, parser):
		bad_offer = self._good_supplier_offer() | {"displayStarLevel": "not-a-number"}
		good_offer = self._good_supplier_offer()

		suppliers = parser._suppliers_appender(offers_list=[bad_offer, good_offer], suppliers=[], divs=[])

		assert len(suppliers) == 1
		assert suppliers[0]["name"] == "shenzhen acme co."


def test_missing_folder_raises_type_error():
	# _html_files_explorer is decorated with @logger.catch(FileNotFoundError),
	# whose default reraise=False swallows the exception and returns None
	# instead of propagating it — despite the method's own docstring claiming
	# `:raises FileNotFoundError:`. The FileNotFoundError never surfaces;
	# iterating over the swallowed None blows up with a TypeError instead.
	parser = PageParser(targeted_folder="does/not/exist")
	with pytest.raises(TypeError):
		parser.detected_suppliers()


CARDS_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "scraped_pages_cards"


class TestHtmlCardFallback:
	"""Since 2026-11 the results page no longer embeds the `_offer_list` JSON:
	products only exist in the `.fy26-product-card` HTML. The synthetic
	fixture mirrors that markup (see tests/fixtures/scraped_pages_cards/).
	"""

	@pytest.fixture
	def cards_parser(self):
		return PageParser(targeted_folder=CARDS_FIXTURES_DIR)

	def test_products_are_read_from_cards_when_json_is_absent(self, cards_parser):
		products = {p["name"]: p for p in cards_parser.detected_products()}
		# 3 well-formed cards; the malformed 4th one is skipped, not fatal.
		assert set(products) == {
			"acme wireless earbuds pro x",
			"acme wireless earbuds lite",
			"globex bluetooth headset",
		}

	def test_product_fields_from_card(self, cards_parser):
		products = {p["name"]: p for p in cards_parser.detected_products()}
		pro_x = products["acme wireless earbuds pro x"]
		assert pro_x["min_price"] == 6.47
		assert pro_x["max_price"] == 12.77
		assert pro_x["minimum_to_order"] == 2.0
		assert pro_x["ordered_or_sold"] == 1474.0
		assert pro_x["review_score"] == 4.9
		assert pro_x["review_count"] == 121.0
		assert pro_x["supplied_by"] == "shenzhen acme co., ltd."
		# Not shown on the cards anymore: neutral defaults, never guessed.
		assert pro_x["product_score"] == 0.0
		assert pro_x["shipping_time_score"] == 0.0
		assert pro_x["certifications"] == ""

	def test_single_price_and_missing_sold_and_review(self, cards_parser):
		products = {p["name"]: p for p in cards_parser.detected_products()}
		headset = products["globex bluetooth headset"]
		assert headset["min_price"] == headset["max_price"] == 15.99
		assert headset["ordered_or_sold"] == 0.0
		assert headset["review_score"] == 0.0
		assert headset["review_count"] == 0.0

	def test_suppliers_from_cards_are_deduped(self, cards_parser):
		suppliers = {s["name"]: s for s in cards_parser.detected_suppliers()}
		assert set(suppliers) == {"shenzhen acme co., ltd.", "globex trading llc"}

	def test_supplier_fields_from_card(self, cards_parser):
		suppliers = {s["name"]: s for s in cards_parser.detected_suppliers()}
		acme = suppliers["shenzhen acme co., ltd."]
		assert acme["verified_type"] == "verified"
		assert acme["sopi_level"] == 3
		assert acme["country_name"] == "chine"
		assert acme["gold_supplier_year"] == "6"
		assert acme["supplier_service_score"] == 0.0
		globex = suppliers["globex trading llc"]
		assert globex["verified_type"] == "unverified"
		assert globex["sopi_level"] == 0
		assert globex["country_name"] == "états-unis"
		assert globex["gold_supplier_year"] == "1"

	def test_card_rows_pass_the_data_quality_checks(self, cards_parser):
		from sourcing_intel_cli.data_quality import run_quality_checks

		suppliers = cards_parser.detected_suppliers()
		products = cards_parser.detected_products()
		clean_suppliers, clean_products, issues = run_quality_checks(suppliers, products)
		assert len(clean_suppliers) == 2
		assert len(clean_products) == 3
		assert issues == []

	def test_json_is_still_preferred_when_present(self, parser):
		# The original fixture embeds the JSON: its values (not the card
		# fallback's defaults) must still be used.
		supplier = parser.detected_suppliers()[0]
		assert supplier["supplier_service_score"] == 4.7
