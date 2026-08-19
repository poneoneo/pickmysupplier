"""Tests for chart_builder.py — deterministic chart-type suggestion and
ECharts option construction from an NL-search result dataframe.

Pure logic, no network/Streamlit/LLM involved.
"""

from __future__ import annotations

import pandas as pd

from sourcing_intel_cli.chart_builder import CHART_TYPES, build_chart, build_map_option, suggest_chart_type


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

	def test_map_keyword_suggests_map(self):
		assert suggest_chart_type("Quels pays sont représentés parmi les fournisseurs ?") == "map"
		assert suggest_chart_type("Montre-moi une carte des fournisseurs") == "map"

	def test_compare_keyword_still_wins_over_pays_for_the_existing_example_question(self):
		# Regression guard: "compar" must still be checked before the map
		# keywords, so this existing example question (already documented
		# in app.py as resolving to "Barres") doesn't silently start
		# resolving to "map" once map keywords are added.
		assert suggest_chart_type("Compare le prix moyen des produits par pays fournisseur.") == "bar"


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

	def test_every_chart_type_gets_zoom_and_screenshot_toolbox(self):
		# Same infra for all four types, via the shared _base_option — zoom
		# in/out (mouse wheel + slider, via dataZoom) and a "save as image"
		# button (screenshot) so charts are usable beyond their fixed
		# on-page size without needing custom JS.
		for chart_type, df in [
			("histogram", self._df()),
			("bar", self._df()),
			("box", pd.DataFrame({"country_name": ["chine", "inde"], "min_price": [1.0, 2.0]})),
			("scatter", self._df()),
		]:
			option = build_chart(df, chart_type)
			assert "saveAsImage" in option["toolbox"]["feature"], chart_type
			assert option["dataZoom"][0]["type"] == "inside"
			assert any(dz["type"] == "slider" for dz in option["dataZoom"]), chart_type

	def test_long_title_wraps_onto_multiple_lines(self):
		# ECharts never wraps title.text on its own — a long NL question used
		# as a chart title used to overflow the container and get hard-clipped
		# mid-word (confirmed via a real screenshot). Wrapping at word
		# boundaries into "\n"-joined lines is what ECharts' title component
		# actually respects as line breaks.
		long_title = (
			"Y a-t-il une corrélation entre le score du produit et le score "
			"de service du fournisseurs ? (Nuage de points)"
		)
		option = build_chart(self._df(), "bar", title=long_title)
		assert "\n" in option["title"]["text"]
		assert all(len(line) <= 55 for line in option["title"]["text"].split("\n"))
		# No word is split across the break — every wrapped line ends on a
		# real word boundary, joining back to the original text unchanged.
		assert option["title"]["text"].replace("\n", " ") == long_title

	def test_short_title_is_not_wrapped(self):
		option = build_chart(self._df(), "bar", title="Top 5")
		assert option["title"]["text"] == "Top 5"

	def test_every_chart_type_centers_the_x_axis_name(self):
		# Same problem _VERTICAL_AXIS_NAME fixed for the y-axis, but for the
		# x-axis: ECharts' default nameLocation="end" puts the name at the
		# axis's right end, which overflowed the container exactly like the
		# y-axis name did before that fix (confirmed via a real screenshot:
		# "product_score" rendered as "product_scc").
		for chart_type, df in [
			("histogram", self._df()),
			("bar", self._df()),
			("box", pd.DataFrame({"country_name": ["chine", "inde"], "min_price": [1.0, 2.0]})),
			("scatter", self._df()),
		]:
			option = build_chart(df, chart_type)
			assert option["xAxis"]["nameLocation"] == "middle", chart_type
			assert option["xAxis"]["nameGap"] > 0, chart_type

	def test_horizontal_bar_centers_the_x_axis_name_too(self):
		# In the horizontal branch, the *value* axis (not the category axis)
		# becomes the x-axis — it needs the same centered-name treatment,
		# not the vertical one (that stays reserved for whichever axis is
		# actually the y-axis).
		from sourcing_intel_cli.chart_builder import build_bar_option

		df = pd.DataFrame({"supplier_name": ["Acme", "Beta"], "supplier_service_score": [4.8, 4.5]})
		option = build_bar_option(df, "supplier_name", "supplier_service_score", "Top", horizontal=True)
		assert option["xAxis"]["nameLocation"] == "middle"
		assert option["xAxis"]["nameGap"] > 0

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

	def test_bar_nan_value_becomes_none_not_nan(self):
		df = pd.DataFrame(
			{
				"supplier_name": ["Acme", "Beta", "Gamma"],
				"supplier_service_score": [4.8, float("nan"), 4.2],
			}
		)
		option = build_chart(df, "bar")
		assert option["series"][0]["data"][1] is None

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
		categories = option["xAxis"]["data"]
		# pandas.Series([1.0, 3.0]).quantile([0, 0.25, 0.5, 0.75, 1]).tolist()
		chine_index = categories.index("chine")
		assert option["series"][0]["data"][chine_index] == [1.0, 1.5, 2.0, 2.5, 3.0]

	def test_scatter_uses_two_numeric_columns(self):
		option = build_chart(self._df(), "scatter")
		assert option["series"][0]["type"] == "scatter"
		assert option["series"][0]["data"] == [[4.8, 1.2], [4.5, 3.4], [4.2, 2.1]]

	def test_map_counts_rows_per_country_and_translates_to_english(self):
		df = pd.DataFrame(
			{"country_name": ["chine", "chine", "inde", "espagne"], "min_price": [1, 2, 3, 4]}
		)
		option = build_chart(df, "map")
		assert option["series"][0]["type"] == "map"
		assert option["series"][0]["map"] == "world"
		by_name = {d["name"]: d["value"] for d in option["series"][0]["data"]}
		assert by_name == {"China": 2, "India": 1, "Spain": 1}

	def test_map_skips_unmapped_countries_without_crashing(self):
		# "hong-kong" isn't its own region in the world map used here (a
		# real, confirmed case from this project's actual scraped data) —
		# must be silently dropped, not crash the whole chart.
		df = pd.DataFrame({"country_name": ["chine", "hong-kong", "narnia"]})
		option = build_chart(df, "map")
		names = {d["name"] for d in option["series"][0]["data"]}
		assert names == {"China"}

	def test_map_prefers_a_country_named_column_over_other_categoricals(self):
		# Product/supplier *names* aren't country names — build_chart's
		# generic "first categorical column" rule would otherwise hand
		# build_map_option a column it can never match against the map,
		# silently producing an empty map even when a real country column
		# is right there in the same dataframe.
		df = pd.DataFrame(
			{
				"supplier_name": ["Acme", "Beta"],
				"country_name": ["chine", "inde"],
				"min_price": [1.0, 2.0],
			}
		)
		option = build_chart(df, "map")
		by_name = {d["name"] for d in option["series"][0]["data"]}
		assert by_name == {"China", "India"}

	def test_map_without_any_categorical_column_returns_none(self):
		df = pd.DataFrame({"min_price": [1.0, 2.0]})
		assert build_chart(df, "map") is None

	def test_scatter_with_only_one_numeric_column_returns_none(self):
		df = pd.DataFrame({"supplier_name": ["Acme", "Beta"], "min_price": [1.2, 3.4]})
		assert build_chart(df, "scatter") is None

	def test_scatter_adds_trend_line_and_correlation_subtext_for_perfect_correlation(self):
		df = pd.DataFrame({"product_score": [1.0, 2.0, 3.0, 4.0], "min_price": [2.0, 4.0, 6.0, 8.0]})
		option = build_chart(df, "scatter")
		assert len(option["series"]) == 2
		trend = option["series"][1]
		assert trend["type"] == "line"
		rounded = [[round(x, 6), round(y, 6)] for x, y in trend["data"]]
		assert rounded == [[1.0, 2.0], [4.0, 8.0]]
		assert "ρ = 1.00" in option["title"]["subtext"]
		assert "100%" in option["title"]["subtext"]
		assert "positive" in option["title"]["subtext"]
		assert "forte" in option["title"]["subtext"]
		assert "Spearman" in option["title"]["subtext"]

	def test_scatter_subtext_says_negative_for_negative_correlation(self):
		df = pd.DataFrame({"product_score": [1.0, 2.0, 3.0, 4.0], "min_price": [8.0, 6.0, 4.0, 2.0]})
		option = build_chart(df, "scatter")
		assert "négative" in option["title"]["subtext"]
		assert "forte" in option["title"]["subtext"]
		assert "ρ = -1.00" in option["title"]["subtext"]

	def test_scatter_subtext_says_no_notable_correlation_below_threshold(self):
		# A symmetric parabola-shaped relationship has zero *linear* correlation.
		df = pd.DataFrame({"product_score": [1.0, 2.0, 3.0, 4.0], "min_price": [1.0, 4.0, 4.0, 1.0]})
		option = build_chart(df, "scatter")
		assert "Pas de corrélation notable" in option["title"]["subtext"]

	def test_scatter_reports_spearman_not_pearson_when_they_disagree(self):
		# x has one extreme outlier (100) that breaks *linearity* but not
		# *monotonicity* — Pearson's r drops well below 1 (~0.59) because the
		# outlier has outsized leverage on the least-squares line, while
		# Spearman's rho (rank-based, immune to that leverage) stays ~1.0.
		# This is the actual scenario a real user's screenshot showed: a
		# dense score cluster plus a couple of outlier points.
		df = pd.DataFrame(
			{
				"product_score": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 100.0],
				"min_price": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0],
			}
		)
		option = build_chart(df, "scatter")
		assert "ρ = 1.00" in option["title"]["subtext"]
		assert "0.59" not in option["title"]["subtext"]  # the Pearson value must not leak through

	def test_scatter_trend_line_still_fits_raw_values_not_ranks(self):
		# The visual trend line stays an ordinary least-squares fit on the
		# raw values (so it's drawn in the same coordinate space as the
		# actual points) even though the quoted correlation switched to
		# Spearman — only the reported statistic changes, not the line.
		df = pd.DataFrame({"product_score": [1.0, 2.0, 3.0, 4.0], "min_price": [2.0, 4.0, 6.0, 8.0]})
		option = build_chart(df, "scatter")
		trend = option["series"][1]
		rounded = [[round(x, 6), round(y, 6)] for x, y in trend["data"]]
		assert rounded == [[1.0, 2.0], [4.0, 8.0]]

	def test_scatter_value_axis_name_does_not_overlap_title(self):
		# ECharts' default yAxis.nameLocation ("end") floats the axis name at
		# the top of the axis — the same corner as title/subtext, which
		# visually collided with the correlation subtext. "middle" + a
		# rotated label along the axis avoids that regardless of subtext length.
		option = build_chart(self._df(), "scatter")
		assert option["yAxis"]["nameLocation"] == "middle"
		assert option["yAxis"]["nameGap"] > 0
		assert option["yAxis"]["nameRotate"] == 90

	def test_scatter_skips_trend_line_when_x_is_constant(self):
		# A vertical line of points has no well-defined slope/correlation.
		df = pd.DataFrame({"product_score": [4.0, 4.0, 4.0], "min_price": [1.0, 2.0, 3.0]})
		option = build_chart(df, "scatter")
		assert len(option["series"]) == 1
		assert option["title"]["subtext"] == ""

	def test_scatter_skips_trend_line_with_fewer_than_two_points(self):
		df = pd.DataFrame({"product_score": [4.0], "min_price": [1.0]})
		option = build_chart(df, "scatter")
		assert len(option["series"]) == 1
		assert option["title"]["subtext"] == ""

	def test_bar_averages_duplicate_categories_instead_of_one_bar_per_row(self):
		# "Compare le prix moyen par pays" style questions return one row
		# per product, not one row per country — plotting them as-is used
		# to produce one unreadable bar per row (168 bars for 168 products)
		# instead of one bar per country. A bar chart with a repeated
		# category should average the value for that category, matching
		# what the fixed "top 10 suppliers" dashboard chart already did by
		# hand before calling this function.
		df = pd.DataFrame(
			{
				"country_name": ["chine", "chine", "inde"],
				"min_price": [10.0, 20.0, 5.0],
			}
		)
		option = build_chart(df, "bar")
		assert option["xAxis"]["data"] == ["chine", "inde"]
		assert option["series"][0]["data"] == [15.0, 5.0]

	def test_bar_leaves_already_unique_categories_unchanged(self):
		# Same behavior as before this fix when every category already
		# appears exactly once (mean of one value is that value).
		option = build_chart(self._df(), "bar")
		assert option["xAxis"]["data"] == ["Acme", "Beta", "Gamma"]
		assert option["series"][0]["data"] == [4.8, 4.5, 4.2]

	def test_bar_nan_category_row_is_dropped(self):
		# A NaN category (as opposed to a NaN value, see
		# test_bar_nan_value_becomes_none_not_nan) can't be sanitized into a
		# meaningful bar — the row is dropped entirely rather than leaking a
		# bare NaN into the category axis data sent to st_echarts.
		df = pd.DataFrame(
			{
				"supplier_name": ["Acme", None, "Gamma"],
				"supplier_service_score": [4.8, 4.5, 4.2],
			}
		)
		option = build_chart(df, "bar")
		assert None not in option["xAxis"]["data"]
		assert len(option["xAxis"]["data"]) == 2
		assert option["series"][0]["data"] == [4.8, 4.2]

	def test_bar_category_axis_shows_every_label(self):
		option = build_chart(self._df(), "bar")
		assert option["xAxis"]["axisLabel"] == {"interval": 0, "rotate": 30}

	def test_box_category_axis_shows_every_label(self):
		df = pd.DataFrame(
			{"country_name": ["chine", "chine", "inde"], "min_price": [1.0, 3.0, 2.0]}
		)
		option = build_chart(df, "box")
		assert option["xAxis"]["axisLabel"] == {"interval": 0, "rotate": 30}

	def test_histogram_has_grid_contain_label(self):
		option = build_chart(self._df(), "histogram")
		assert option["grid"] == {"containLabel": True}

	def test_bar_has_grid_contain_label(self):
		option = build_chart(self._df(), "bar")
		assert option["grid"] == {"containLabel": True}

	def test_box_has_grid_contain_label(self):
		df = pd.DataFrame(
			{"country_name": ["chine", "chine", "inde"], "min_price": [1.0, 3.0, 2.0]}
		)
		option = build_chart(df, "box")
		assert option["grid"] == {"containLabel": True}

	def test_scatter_has_grid_contain_label(self):
		option = build_chart(self._df(), "scatter")
		assert option["grid"] == {"containLabel": True}


class TestBuildBarOptionHorizontal:
	def test_horizontal_swaps_axes(self):
		from sourcing_intel_cli.chart_builder import build_bar_option

		df = pd.DataFrame({"supplier_name": ["Acme", "Beta"], "supplier_service_score": [4.8, 4.5]})
		option = build_bar_option(df, "supplier_name", "supplier_service_score", "Top", horizontal=True)
		assert option["yAxis"]["data"] == ["Acme", "Beta"]
		assert option["xAxis"]["name"] == "supplier_service_score"


def test_chart_types_lists_all_supported_types():
	assert set(CHART_TYPES) == {"none", "auto", "histogram", "bar", "box", "scatter", "map"}


class TestBuildMapOption:
	def test_builds_valid_map_series_directly(self):
		df = pd.DataFrame({"country_name": ["chine", "inde", "inde"]})
		option = build_map_option(df, "country_name", "Pays des fournisseurs")
		series = option["series"][0]
		assert series["type"] == "map"
		assert series["map"] == "world"
		assert {d["name"]: d["value"] for d in series["data"]} == {"China": 1, "India": 2}

	def test_empty_when_nothing_maps(self):
		df = pd.DataFrame({"country_name": ["narnia", "atlantis"]})
		option = build_map_option(df, "country_name", "Pays")
		assert option["series"][0]["data"] == []
