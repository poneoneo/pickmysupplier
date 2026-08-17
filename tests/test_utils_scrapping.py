"""Unit tests for sourcing_intel_cli.utils_scrapping — pure parsing helpers."""

from __future__ import annotations

import pytest

from sourcing_intel_cli.utils_scrapping import (
	clean_product_title,
	country_name,
	custom_minium_to_oder,
	get_product_certification,
	get_product_price,
	is_alibaba_guaranteed,
	parse_moq_text,
	parse_sold_count,
	safe_float,
)


class TestSafeFloat:
	def test_parses_valid_number(self):
		assert safe_float("4.5") == 4.5

	def test_falls_back_to_default_on_empty_string(self):
		assert safe_float("", default=0.0) == 0.0

	def test_falls_back_to_default_on_none(self):
		assert safe_float(None, default=1.0) == 1.0


class TestGetProductPrice:
	def test_single_price_with_dollar_sign(self):
		assert get_product_price("$1.99", which="min") == 1.99

	def test_range_min(self):
		assert get_product_price("$1.99-$5.00", which="min") == 1.99

	def test_range_max(self):
		assert get_product_price("$1.99-$5.00", which="max") == 5.00

	def test_comma_thousands_separator(self):
		# "$1,234.56" -> comma normalized to dot -> "1.234.56" -> collapsed to 1234.56
		assert get_product_price("$1,234.56", which="min") == 1234.56

	def test_thousands_separator_with_currency_code_glued_to_tail(self):
		# Polish zloty rendered without a separating symbol: "30.171.21PLN"
		# has two dots (thousands + decimal) and "PLN" stuck straight onto
		# the decimal digits — used to raise ValueError, see CLAUDE.md.
		assert get_product_price("30.171.21PLN", which="min") == 30171.21


class TestIsAlibabaGuaranteed:
	def test_false_string_is_false(self):
		assert is_alibaba_guaranteed("false") is False

	def test_anything_else_is_true(self):
		assert is_alibaba_guaranteed("true") is True


class TestGetProductCertification:
	def test_flattens_certification_names(self):
		offer = {
			"certifications": [
				{"prefixIcons": [{"name": "CE"}, {"name": "RoHS"}]},
				{"prefixIcons": [{"name": "ISO9001"}]},
			]
		}
		assert get_product_certification(offer) == "CE,RoHS,ISO9001"

	def test_no_certifications_returns_empty_string(self):
		assert get_product_certification({}) == ""


class TestCleanProductTitle:
	def test_strips_html_fragment(self):
		raw = "<img src='badge.png'/><span> </span>G01 Wireless Neckband Headphone"
		assert clean_product_title(raw) == "G01 Wireless Neckband Headphone"


class TestParseMoqText:
	def test_extracts_quantity(self):
		assert parse_moq_text("Min. order: 1,000 pieces") == 1000.0

	def test_returns_zero_when_unparsable(self):
		assert parse_moq_text("no number here") == 0.0


class TestParseSoldCount:
	def test_extracts_count(self):
		assert parse_sold_count("1,699 sold") == 1699.0

	def test_returns_zero_on_none(self):
		assert parse_sold_count(None) == 0.0

	def test_returns_zero_when_unparsable(self):
		assert parse_sold_count("unavailable") == 0.0


class TestCustomMiniumToOder:
	def test_parses_valid_number(self):
		assert custom_minium_to_oder("50") == 50.0

	def test_returns_zero_on_invalid_string(self):
		assert custom_minium_to_oder("n/a") == 0.0


class TestCountryName:
	def test_known_country_code(self):
		assert country_name("FR") == "france"

	def test_is_case_insensitive(self):
		assert country_name("fr") == "france"

	def test_unknown_code_returns_unknow(self):
		assert country_name("ZZ") == "unknow"


@pytest.mark.parametrize(
	"country_code,expected",
	[("US", "états-unis"), ("CN", "chine"), ("DE", "allemagne")],
)
def test_country_name_common_sourcing_countries(country_code, expected):
	assert country_name(country_code) == expected
