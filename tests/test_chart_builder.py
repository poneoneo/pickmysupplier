"""Tests for chart_builder.py — deterministic chart-type suggestion and
ECharts option construction from an NL-search result dataframe.

Pure logic, no network/Streamlit/LLM involved.
"""

from __future__ import annotations

import pandas as pd

from sourcing_intel_cli.chart_builder import CHART_TYPES, build_chart, suggest_chart_type


class TestSuggestChartType:
	def test_distribution_keyword_suggests_histogram(self):
		assert suggest_chart_type("Quelle est la distribution des prix ?") == "histogram"

	def test_repartition_keyword_suggests_histogram(self):
		assert suggest_chart_type("Répartition des scores produits") == "histogram"

	def test_top_keyword_suggests_bar(self):
		assert suggest_chart_type("Quels sont les 5 meilleurs fournisseurs ?") == "bar"

	def test_compare_keyword_suggests_bar(self):
		assert suggest_chart_type("Compare le prix moyen par pays") == "bar"

	def test_dispersion_keyword_suggests_box(self):
		assert suggest_chart_type("Quelle est la dispersion des prix par pays ?") == "box"

	def test_correlation_keyword_suggests_scatter(self):
		assert suggest_chart_type("Y a-t-il une corrélation entre prix et score ?") == "scatter"

	def test_unmatched_question_falls_back_to_bar(self):
		assert suggest_chart_type("Liste les fournisseurs en Chine") == "bar"

	def test_is_case_insensitive(self):
		assert suggest_chart_type("DISTRIBUTION DES PRIX") == "histogram"


class TestBuildChart:
	def _df(self):
		return pd.DataFrame(
			{
				"supplier_name": ["Acme", "Beta", "Gamma"],
				"supplier_service_score": [4.8, 4.5, 4.2],
				"min_price": [1.2, 3.4, 2.1],
			}
		)

	def test_none_chart_type_returns_none(self):
		assert build_chart(self._df(), "none") is None

	def test_histogram_uses_first_numeric_column(self):
		option = build_chart(self._df(), "histogram")
		assert option["series"][0]["type"] == "bar"
		assert sum(option["series"][0]["data"]) == 3
		assert option["xAxis"]["name"] == "supplier_service_score"

	def test_empty_dataframe_returns_none(self):
		assert build_chart(pd.DataFrame(), "bar") is None

	def test_histogram_without_numeric_column_returns_none(self):
		df = pd.DataFrame({"supplier_name": ["Acme", "Beta"]})
		assert build_chart(df, "histogram") is None

	def test_unknown_chart_type_returns_none(self):
		assert build_chart(self._df(), "not-a-real-type") is None

	def test_bar_uses_categorical_and_numeric_columns(self):
		option = build_chart(self._df(), "bar")
		assert option["series"][0]["type"] == "bar"
		assert option["xAxis"]["data"] == ["Acme", "Beta", "Gamma"]
		assert option["series"][0]["data"] == [4.8, 4.5, 4.2]

	def test_bar_without_categorical_column_returns_none(self):
		df = pd.DataFrame({"min_price": [1.2, 3.4], "max_price": [2.0, 5.0]})
		assert build_chart(df, "bar") is None

	def test_metric_col_is_used_as_value_axis_over_first_numeric_column(self):
		df = pd.DataFrame(
			{
				"supplier_name": ["Acme", "Beta"],
				"product_score": [4.0, 3.5],
				"supplier_service_score": [4.8, 4.5],
			}
		)
		option = build_chart(df, "bar", metric_col="supplier_service_score")
		assert option["series"][0]["data"][0] == 4.8

	def test_metric_col_not_in_dataframe_falls_back_to_first_numeric(self):
		option = build_chart(self._df(), "bar", metric_col="not_a_real_column")
		assert option["series"][0]["data"][0] == 4.8

	def test_box_uses_categorical_and_numeric_columns(self):
		df = pd.DataFrame(
			{
				"country_name": ["chine", "chine", "inde"],
				"min_price": [1.0, 3.0, 2.0],
			}
		)
		option = build_chart(df, "box")
		assert option["series"][0]["type"] == "boxplot"
		assert set(option["xAxis"]["data"]) == {"chine", "inde"}


class TestBuildBarOptionHorizontal:
	def test_horizontal_swaps_axes(self):
		from sourcing_intel_cli.chart_builder import build_bar_option

		df = pd.DataFrame({"supplier_name": ["Acme", "Beta"], "supplier_service_score": [4.8, 4.5]})
		option = build_bar_option(df, "supplier_name", "supplier_service_score", "Top", horizontal=True)
		assert option["yAxis"]["data"] == ["Acme", "Beta"]
		assert option["xAxis"]["name"] == "supplier_service_score"


def test_chart_types_lists_all_supported_types():
	assert set(CHART_TYPES) == {"none", "auto", "histogram", "bar", "box", "scatter"}
