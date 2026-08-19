"""Unit tests for sourcing_intel_cli.data_quality — pure logic, no network/DB."""

from __future__ import annotations

from sourcing_intel_cli.data_quality import (
	run_quality_checks,
	validate_products,
	validate_suppliers,
)


def _supplier(**overrides):
	base = {
		"name": "Shenzhen Acme Co.",
		"verified_type": "gold",
		"sopi_level": 3,
		"country_name": "china",
		"gold_supplier_year": 5,
		"supplier_service_score": 4.5,
	}
	base.update(overrides)
	return base


def _product(**overrides):
	base = {
		"name": "Wireless earbuds - model A",
		"guaranteed_by_alibaba": True,
		"certifications": "CE,RoHS",
		"minimum_to_order": 10.0,
		"ordered_or_sold": 100.0,
		"min_price": 1.5,
		"max_price": 3.0,
		"product_score": 4.5,
		"review_count": 20.0,
		"review_score": 4.8,
		"shipping_time_score": 4.9,
		"is_full_promotion": False,
		"customizable": True,
		"instant_order": False,
		"trade_product": True,
		"supplied_by": "Shenzhen Acme Co.",
	}
	base.update(overrides)
	return base


class TestValidateSuppliers:
	def test_valid_supplier_is_kept(self):
		clean, issues = validate_suppliers([_supplier()])
		assert len(clean) == 1
		assert issues == []

	def test_empty_name_is_rejected(self):
		clean, issues = validate_suppliers([_supplier(name="  ")])
		assert clean == []
		assert len(issues) == 1
		assert issues[0].field == "name"

	def test_duplicate_name_keeps_first_only(self):
		clean, issues = validate_suppliers([_supplier(), _supplier()])
		assert len(clean) == 1
		assert len(issues) == 1
		assert "Duplicate" in issues[0].reason

	def test_negative_sopi_level_is_rejected(self):
		clean, issues = validate_suppliers([_supplier(sopi_level=-1)])
		assert clean == []
		assert issues[0].field == "sopi_level"

	def test_bool_sopi_level_is_rejected(self):
		# bool is a subclass of int in Python — must be explicitly excluded.
		clean, issues = validate_suppliers([_supplier(sopi_level=True)])
		assert clean == []
		assert issues[0].field == "sopi_level"

	def test_non_numeric_service_score_is_rejected(self):
		clean, issues = validate_suppliers([_supplier(supplier_service_score="n/a")])
		assert clean == []
		assert issues[0].field == "supplier_service_score"

	def test_non_numeric_gold_years_is_rejected(self):
		clean, issues = validate_suppliers([_supplier(gold_supplier_year="n/a")])
		assert clean == []
		assert issues[0].field == "gold_supplier_year"


class TestValidateProducts:
	def _valid_supplier_names(self):
		return {"Shenzhen Acme Co."}

	def test_valid_product_is_kept(self):
		clean, issues = validate_products([_product()], self._valid_supplier_names())
		assert len(clean) == 1
		assert issues == []

	def test_empty_name_is_rejected(self):
		clean, issues = validate_products([_product(name="")], self._valid_supplier_names())
		assert clean == []
		assert issues[0].field == "name"

	def test_duplicate_name_from_same_supplier_keeps_first_only(self):
		clean, issues = validate_products(
			[_product(), _product()], self._valid_supplier_names()
		)
		assert len(clean) == 1
		assert len(issues) == 1

	def test_same_name_from_different_suppliers_is_kept(self):
		# Two different suppliers legitimately post the same/similar product
		# title, each at their own price — this must NOT be treated as a
		# duplicate the way the same supplier re-listing the same name is.
		valid = {"Shenzhen Acme Co.", "Guangzhou Beta Co."}
		products = [
			_product(supplied_by="Shenzhen Acme Co.", min_price=1.5),
			_product(supplied_by="Guangzhou Beta Co.", min_price=2.0),
		]
		clean, issues = validate_products(products, valid)
		assert len(clean) == 2
		assert issues == []

	def test_unknown_supplier_is_rejected(self):
		clean, issues = validate_products(
			[_product(supplied_by="Ghost Supplier")], self._valid_supplier_names()
		)
		assert clean == []
		assert issues[0].field == "supplied_by"

	def test_min_price_greater_than_max_price_is_rejected(self):
		clean, issues = validate_products(
			[_product(min_price=10.0, max_price=1.0)], self._valid_supplier_names()
		)
		assert clean == []
		assert issues[0].field == "min_price/max_price"

	def test_negative_price_is_rejected(self):
		clean, issues = validate_products(
			[_product(min_price=-1.0)], self._valid_supplier_names()
		)
		assert clean == []
		assert issues[0].field == "min_price/max_price"

	def test_non_bool_field_is_rejected(self):
		clean, issues = validate_products(
			[_product(is_full_promotion="false")], self._valid_supplier_names()
		)
		assert clean == []
		assert any(i.field == "is_full_promotion" for i in issues)

	def test_negative_numeric_field_is_rejected(self):
		clean, issues = validate_products(
			[_product(review_count=-5.0)], self._valid_supplier_names()
		)
		assert clean == []
		assert any(i.field == "review_count" for i in issues)


class TestRunQualityChecks:
	def test_clean_batch_passes_through(self):
		suppliers, products, issues = run_quality_checks([_supplier()], [_product()])
		assert len(suppliers) == 1
		assert len(products) == 1
		assert issues == []

	def test_product_referencing_rejected_supplier_is_also_rejected(self):
		bad_supplier = _supplier(sopi_level=-1)
		product = _product(supplied_by=bad_supplier["name"])
		suppliers, products, issues = run_quality_checks([bad_supplier], [product])
		assert suppliers == []
		assert products == []
		# one issue for the bad supplier, one for the product that referenced it
		assert len(issues) == 2
