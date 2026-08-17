"""Tests for nl_search.py.

`apply_query_spec`/`build_value_hints` are pure pandas logic — no network.
`build_query_spec` mocks the Groq client — no real API call.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pandas as pd

from sourcing_intel_cli.nl_search import apply_query_spec, build_query_spec, build_value_hints


class TestBuildValueHints:
	def test_includes_low_cardinality_text_column(self):
		df = pd.DataFrame({"country_name": ["chine", "chine", "japon", "espagne"]})
		hint = build_value_hints(df)
		assert "country_name" in hint
		assert "'chine'" in hint
		assert "'japon'" in hint
		assert "'espagne'" in hint

	def test_excludes_high_cardinality_text_column(self):
		df = pd.DataFrame({"product_name": [f"product {i}" for i in range(50)]})
		hint = build_value_hints(df, max_unique=30)
		assert hint == ""

	def test_excludes_numeric_columns(self):
		df = pd.DataFrame({"min_price": [1.0, 2.0, 3.0]})
		assert build_value_hints(df) == ""

	def test_empty_dataframe_returns_empty_string(self):
		assert build_value_hints(pd.DataFrame()) == ""

	def test_drops_nan_values(self):
		df = pd.DataFrame({"country_name": ["chine", None, "japon"]})
		hint = build_value_hints(df)
		assert "None" not in hint
		assert "nan" not in hint.lower()

	def test_values_are_sorted(self):
		df = pd.DataFrame({"country_name": ["japon", "chine", "espagne"]})
		hint = build_value_hints(df)
		line = [line for line in hint.splitlines() if "country_name" in line][0]
		assert line.index("'chine'") < line.index("'espagne'") < line.index("'japon'")

	def test_multiple_qualifying_columns_each_get_a_line(self):
		df = pd.DataFrame(
			{
				"country_name": ["chine", "japon"],
				"verified_type": ["gold", "verified"],
			}
		)
		hint = build_value_hints(df)
		assert "country_name" in hint
		assert "verified_type" in hint


def _df():
	return pd.DataFrame(
		{
			"supplier_name": ["Acme", "Beta", "Gamma", "Delta"],
			"country_name": ["chine", "chine", "japon", "chine"],
			"supplier_service_score": [4.8, 4.5, 4.2, 3.9],
		}
	)


class TestApplyQuerySpec:
	def test_equality_filter(self):
		spec = {"filters": [{"column": "country_name", "op": "==", "value": "chine"}]}
		result = apply_query_spec(_df(), spec)
		assert set(result["country_name"]) == {"chine"}
		assert len(result) == 3

	def test_multiple_equality_filters_on_same_column_are_treated_as_or(self):
		# Regression: the model sometimes emits one "==" filter per value
		# instead of a single "in" filter (e.g. "compare across all
		# countries" -> 8 separate country_name == filters). ANDing them
		# sequentially always yields zero rows (a cell can't equal two
		# different values at once) — the only sensible reading is OR.
		spec = {
			"filters": [
				{"column": "country_name", "op": "==", "value": "chine"},
				{"column": "country_name", "op": "==", "value": "japon"},
			]
		}
		result = apply_query_spec(_df(), spec)
		assert set(result["country_name"]) == {"chine", "japon"}
		assert len(result) == 4

	def test_greater_than_filter(self):
		spec = {"filters": [{"column": "supplier_service_score", "op": ">", "value": 4.3}]}
		result = apply_query_spec(_df(), spec)
		assert set(result["supplier_name"]) == {"Acme", "Beta"}

	def test_in_filter(self):
		spec = {"filters": [{"column": "country_name", "op": "in", "value": ["japon"]}]}
		result = apply_query_spec(_df(), spec)
		assert list(result["supplier_name"]) == ["Gamma"]

	def test_contains_filter(self):
		spec = {"filters": [{"column": "supplier_name", "op": "contains", "value": "et"}]}
		result = apply_query_spec(_df(), spec)
		assert list(result["supplier_name"]) == ["Beta"]

	def test_sort_ascending(self):
		spec = {"sort_by": "supplier_service_score", "ascending": True}
		result = apply_query_spec(_df(), spec)
		assert list(result["supplier_service_score"]) == [3.9, 4.2, 4.5, 4.8]

	def test_sort_descending(self):
		spec = {"sort_by": "supplier_service_score", "ascending": False}
		result = apply_query_spec(_df(), spec)
		assert list(result["supplier_service_score"]) == [4.8, 4.5, 4.2, 3.9]

	def test_limit(self):
		spec = {"sort_by": "supplier_service_score", "ascending": False, "limit": 2}
		result = apply_query_spec(_df(), spec)
		assert len(result) == 2

	def test_no_keep_defaults_to_head_of_the_sort(self):
		spec = {"sort_by": "supplier_service_score", "ascending": True, "limit": 2}
		result = apply_query_spec(_df(), spec)
		assert list(result["supplier_service_score"]) == [3.9, 4.2]

	def test_keep_highest_with_ascending_display_takes_tail(self):
		# The exact reported bug: "top N, ascending" — the 2 highest scores,
		# displayed lowest-to-highest, not the 2 lowest.
		spec = {
			"sort_by": "supplier_service_score",
			"ascending": True,
			"keep": "highest",
			"limit": 2,
		}
		result = apply_query_spec(_df(), spec)
		assert list(result["supplier_service_score"]) == [4.5, 4.8]

	def test_keep_highest_with_descending_display_takes_head(self):
		spec = {
			"sort_by": "supplier_service_score",
			"ascending": False,
			"keep": "highest",
			"limit": 2,
		}
		result = apply_query_spec(_df(), spec)
		assert list(result["supplier_service_score"]) == [4.8, 4.5]

	def test_keep_lowest_with_ascending_display_takes_head(self):
		spec = {
			"sort_by": "supplier_service_score",
			"ascending": True,
			"keep": "lowest",
			"limit": 2,
		}
		result = apply_query_spec(_df(), spec)
		assert list(result["supplier_service_score"]) == [3.9, 4.2]

	def test_keep_lowest_with_descending_display_takes_tail(self):
		spec = {
			"sort_by": "supplier_service_score",
			"ascending": False,
			"keep": "lowest",
			"limit": 2,
		}
		result = apply_query_spec(_df(), spec)
		assert list(result["supplier_service_score"]) == [4.2, 3.9]

	def test_column_selection_and_order(self):
		spec = {"columns": ["country_name", "supplier_name"]}
		result = apply_query_spec(_df(), spec)
		assert list(result.columns) == ["country_name", "supplier_name"]

	def test_filter_with_null_value_is_ignored(self):
		# Regression: pandas silently returns all-False for `series >= None`
		# (no exception raised) — a redundant null-value filter from the
		# model must not be allowed to wipe out an otherwise-correct result.
		spec = {
			"filters": [
				{"column": "country_name", "op": "==", "value": "chine"},
				{"column": "supplier_service_score", "op": ">=", "value": None},
			]
		}
		result = apply_query_spec(_df(), spec)
		assert len(result) == 3

	def test_unknown_column_in_filter_is_ignored(self):
		spec = {"filters": [{"column": "not_a_real_column", "op": "==", "value": "x"}]}
		result = apply_query_spec(_df(), spec)
		assert len(result) == len(_df())

	def test_unknown_op_is_ignored(self):
		spec = {"filters": [{"column": "country_name", "op": "not_a_real_op", "value": "chine"}]}
		result = apply_query_spec(_df(), spec)
		assert len(result) == len(_df())

	def test_unknown_sort_column_is_ignored(self):
		spec = {"sort_by": "not_a_real_column"}
		result = apply_query_spec(_df(), spec)
		assert list(result["supplier_name"]) == list(_df()["supplier_name"])

	def test_unknown_columns_in_column_list_are_dropped(self):
		spec = {"columns": ["supplier_name", "not_a_real_column"]}
		result = apply_query_spec(_df(), spec)
		assert list(result.columns) == ["supplier_name"]

	def test_non_dict_spec_returns_dataframe_unchanged(self):
		result = apply_query_spec(_df(), "not a dict")
		assert list(result.columns) == list(_df().columns)

	def test_full_pipeline_matches_the_reported_bug_scenario(self):
		spec = {
			"filters": [{"column": "country_name", "op": "==", "value": "chine"}],
			"sort_by": "supplier_service_score",
			"ascending": True,
			"limit": 2,
			"columns": ["supplier_name", "supplier_service_score"],
		}
		result = apply_query_spec(_df(), spec)
		assert list(result.columns) == ["supplier_name", "supplier_service_score"]
		assert list(result["supplier_name"]) == ["Delta", "Beta"]


def _df_one_supplier_per_two_products():
	# Mimics the real Product<->Supplier join: each supplier appears once
	# per product it sells, so a supplier-level answer sees repeated rows.
	return pd.DataFrame(
		{
			"product_name": ["Widget A", "Widget B", "Gadget A", "Gadget B"],
			"supplier_name": ["Acme", "Acme", "Beta", "Beta"],
			"supplier_service_score": [4.8, 4.8, 4.5, 4.5],
		}
	)


class TestApplyQuerySpecDeduplication:
	def test_duplicate_rows_collapse_to_one_after_column_selection(self):
		# Regression: a supplier appearing twice (once per product) rendered
		# as a visually-inflated bar in Plotly (repeated x-category values
		# get stacked within one trace — 4.8 shown twice looked like ~9.6).
		spec = {"columns": ["supplier_name", "supplier_service_score"]}
		result = apply_query_spec(_df_one_supplier_per_two_products(), spec)
		assert len(result) == 2
		assert sorted(result["supplier_name"]) == ["Acme", "Beta"]

	def test_limit_counts_unique_rows_not_raw_rows(self):
		# "top 1" must return 1 unique supplier, not 1 raw (possibly
		# duplicated) row that then collapses to fewer after dedup.
		spec = {
			"sort_by": "supplier_service_score",
			"ascending": False,
			"limit": 1,
			"columns": ["supplier_name", "supplier_service_score"],
		}
		result = apply_query_spec(_df_one_supplier_per_two_products(), spec)
		assert len(result) == 1
		assert result["supplier_name"].iloc[0] == "Acme"

	def test_no_columns_specified_dedupes_on_full_row(self):
		df = pd.DataFrame({"a": [1, 1, 2], "b": ["x", "x", "y"]})
		result = apply_query_spec(df, {})
		assert len(result) == 2


def _mock_groq_client(response_dict: dict):
	client = MagicMock()
	completion = MagicMock()
	completion.choices = [MagicMock(message=MagicMock(content=json.dumps(response_dict)))]
	client.chat.completions.create.return_value = completion
	return client


class TestBuildQuerySpec:
	"""GROQ_API_KEY is patched to a dummy value in every test here — these
	must pass identically in CI (no .env, real key is empty) and locally.
	"""

	def test_returns_parsed_json_spec(self):
		spec_dict = {
			"filters": [{"column": "country_name", "op": "==", "value": "chine"}],
			"sort_by": "supplier_service_score",
			"ascending": True,
			"limit": 5,
			"columns": ["supplier_name", "supplier_service_score"],
		}
		with (
			patch("sourcing_intel_cli.nl_search.GROQ_API_KEY", "test-key"),
			patch("sourcing_intel_cli.nl_search.Groq", return_value=_mock_groq_client(spec_dict)),
		):
			result = build_query_spec("meilleurs fournisseurs en chine", _df())
		assert result == spec_dict

	def test_uses_json_mode_and_zero_temperature(self):
		client = _mock_groq_client({"filters": []})
		with (
			patch("sourcing_intel_cli.nl_search.GROQ_API_KEY", "test-key"),
			patch("sourcing_intel_cli.nl_search.Groq", return_value=client),
		):
			build_query_spec("une question", _df())
		kwargs = client.chat.completions.create.call_args.kwargs
		assert kwargs["response_format"] == {"type": "json_object"}
		assert kwargs["temperature"] == 0

	def test_raises_runtime_error_on_invalid_json(self):
		client = MagicMock()
		completion = MagicMock()
		completion.choices = [MagicMock(message=MagicMock(content="not json"))]
		client.chat.completions.create.return_value = completion
		with (
			patch("sourcing_intel_cli.nl_search.GROQ_API_KEY", "test-key"),
			patch("sourcing_intel_cli.nl_search.Groq", return_value=client),
		):
			try:
				build_query_spec("une question", _df())
				assert False, "expected RuntimeError"
			except RuntimeError:
				pass

	def test_raises_runtime_error_when_api_key_missing(self):
		with patch("sourcing_intel_cli.nl_search.GROQ_API_KEY", ""):
			try:
				build_query_spec("une question", _df())
				assert False, "expected RuntimeError"
			except RuntimeError:
				pass
