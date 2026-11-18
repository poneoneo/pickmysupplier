"""Tests for data_coverage.py — pure pandas, no network."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from sourcing_intel_cli.chart_builder import suggest_chart_type
from sourcing_intel_cli.data_coverage import (
	EXAMPLE_QUESTIONS,
	example_questions,
	mark_missing_values,
	missing_share,
	unavailable_columns,
	unavailable_fields_mentioned,
)


def _scraped_df() -> pd.DataFrame:
	"""Shape of a live scrape from the search API (2026-11): no verification
	badge, the five boolean flags never sourced, some blank ratings (0.0)."""
	return pd.DataFrame({
		"product_name": ["a", "b", "c", "d"],
		"min_price": [1.0, 2.0, 3.0, 4.0],
		"product_score": [4.8, 0.0, 4.5, 5.0],
		"review_count": [10.0, 0.0, 3.0, 8.0],
		"review_score": [4.9, 0.0, 4.4, 5.0],
		"shipping_time_score": [4.7, 4.2, 0.0, 4.9],
		"supplier_service_score": [4.6, 0.0, 0.0, 4.1],
		"certifications": ["FCC,CE", "", "CE", ""],
		"trade_product": [0, 0, 0, 0],
		"alibaba_guranteed": [0, 0, 0, 0],
		"is_full_promotion": [0, 0, 0, 0],
		"is_customizable": [0, 0, 0, 0],
		"is_instant_order": [0, 0, 0, 0],
		"ordered_or_sold": [100.0, 0.0, 5.0, 12.0],
		"supplier_name": ["s1", "s2", "s3", "s1"],
		"country_name": ["chine", "chine", "inde", "chine"],
		"years_as_gold_supplier": [3, 1, 6, 3],
		"verification_mode": ["unknown"] * 4,
	})


def _demo_like_df() -> pd.DataFrame:
	"""Every field populated, like the synthetic demo dataset."""
	df = _scraped_df()
	df["product_score"] = [4.8, 3.2, 4.5, 5.0]
	df["review_score"] = [4.9, 3.0, 4.4, 5.0]
	df["shipping_time_score"] = [4.7, 4.2, 3.9, 4.9]
	df["supplier_service_score"] = [4.6, 3.1, 3.5, 4.1]
	for col in ("trade_product", "alibaba_guranteed", "is_full_promotion", "is_customizable", "is_instant_order"):
		df[col] = [1, 0, 1, 0]
	df["verification_mode"] = ["verified", "gold", "unverified", "verified"]
	return df


class TestMarkMissingValues:
	def test_blank_ratings_become_missing_not_zero(self):
		# A 0 out of 5 isn't a rating: the site left the field blank. Kept
		# as 0, it drags every average down.
		df = mark_missing_values(_scraped_df())
		assert math.isnan(df.loc[1, "product_score"])
		assert math.isnan(df.loc[1, "supplier_service_score"])
		assert df["supplier_service_score"].mean() == pytest.approx((4.6 + 4.1) / 2)

	def test_real_ratings_and_counts_are_kept(self):
		df = mark_missing_values(_scraped_df())
		assert df.loc[0, "product_score"] == 4.8
		# 0 reviews / 0 sold are real counts, not missing values.
		assert df.loc[1, "review_count"] == 0.0
		assert df.loc[1, "ordered_or_sold"] == 0.0

	def test_unknown_verification_becomes_missing(self):
		df = mark_missing_values(_scraped_df())
		assert df["verification_mode"].isna().all()

	def test_does_not_modify_the_input(self):
		original = _scraped_df()
		mark_missing_values(original)
		assert original.loc[1, "product_score"] == 0.0


class TestUnavailableColumns:
	def test_scraped_dataset(self):
		unavailable = unavailable_columns(mark_missing_values(_scraped_df()))
		assert set(unavailable) == {
			"verification_mode",
			"trade_product",
			"alibaba_guranteed",
			"is_full_promotion",
			"is_customizable",
			"is_instant_order",
		}

	def test_partially_missing_ratings_stay_available(self):
		unavailable = unavailable_columns(mark_missing_values(_scraped_df()))
		assert "supplier_service_score" not in unavailable

	def test_column_entirely_blank_is_unavailable(self):
		df = _scraped_df()
		df["supplier_service_score"] = 0.0
		df["certifications"] = ""
		unavailable = unavailable_columns(mark_missing_values(df))
		assert "supplier_service_score" in unavailable
		assert "certifications" in unavailable

	def test_complete_dataset_has_nothing_unavailable(self):
		assert unavailable_columns(mark_missing_values(_demo_like_df())) == []


class TestMissingShare:
	def test_reports_partially_blank_ratings_only(self):
		share = missing_share(mark_missing_values(_scraped_df()))
		# 2 of 4 rows have a blank supplier service score.
		assert share["supplier_service_score"] == pytest.approx(0.5)
		assert share["product_score"] == pytest.approx(0.25)
		# Fully missing (unavailable) columns are reported elsewhere.
		assert "verification_mode" not in share


class TestExampleQuestions:
	def test_declared_chart_matches_what_auto_actually_picks(self):
		# The page says the chart in parentheses is "verified, not just
		# indicative" — keep that true for every template.
		for template, _required, chart in EXAMPLE_QUESTIONS:
			question = template.format(country="chine", certification="CE")
			if chart == "Table":
				continue
			assert suggest_chart_type(question) == chart.lower().replace("world map", "map").replace(
				"box plot", "box"
			), question

	def test_scraped_dataset_never_suggests_unavailable_fields(self):
		df = mark_missing_values(_scraped_df())
		questions = " ".join(q for q, _ in example_questions(df, unavailable_columns(df)))
		assert "verified" not in questions.lower()
		assert "trade assurance" not in questions.lower()
		assert "supplier_service_score" in questions  # partially blank, still queryable

	def test_complete_dataset_gets_the_verification_question(self):
		df = mark_missing_values(_demo_like_df())
		questions = " ".join(q for q, _ in example_questions(df, unavailable_columns(df)))
		assert "verified" in questions.lower()

	def test_uses_values_present_in_the_data(self):
		df = mark_missing_values(_scraped_df())
		questions = " ".join(q for q, _ in example_questions(df, unavailable_columns(df)))
		assert "chine" in questions  # most common country
		assert "CE certification" in questions  # most common certification


class TestUnavailableFieldsMentioned:
	def test_flags_a_question_about_a_missing_field(self):
		mentioned = unavailable_fields_mentioned(
			"List verified suppliers in China", ["verification_mode", "trade_product"]
		)
		assert mentioned == ["verification_mode"]

	def test_ignores_fields_that_are_available(self):
		assert unavailable_fields_mentioned("verified suppliers", ["trade_product"]) == []

	def test_trade_assurance_wording(self):
		assert unavailable_fields_mentioned(
			"suppliers with Trade Assurance", ["trade_product"]
		) == ["trade_product"]
