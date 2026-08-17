"""Deterministic chart-type selection and ECharts option construction for
the natural-language search results (see `nl_search.py` for how the result
dataframe itself is produced — deterministically, not LLM-generated code)
and for the fixed dashboard charts in `app.py`.

Chart selection stays outside the LLM entirely: either the user picks a
chart type explicitly, or `suggest_chart_type` maps the question's wording
to one of a fixed set of chart types, and `build_chart` renders it from
whatever columns the result dataframe actually has, as an ECharts `option`
dict passed straight to `streamlit_echarts.st_echarts`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

CHART_TYPES = ("none", "auto", "histogram", "bar", "box", "scatter")

# Matches the dark reference design's chart series colors (blue/red/pink).
SERIES_COLORS = ["#5b8ff9", "#e8524c", "#f6a5c0"]

_KEYWORD_TO_CHART_TYPE = (
	(("distribution", "répartition", "repartition"), "histogram"),
	(("dispersion", "écart", "ecart", "boîte", "boite"), "box"),
	(("corrélation", "correlation", " vs ", "relation entre"), "scatter"),
	(("top", "meilleur", "classement", "compar"), "bar"),
)


def suggest_chart_type(question: str) -> str:
	"""Map a natural-language question to a chart type using keyword matching.

	:param question: The user's natural-language question.
	:type question: str
	:return: One of `"histogram"`, `"bar"`, `"box"`, `"scatter"` — falls back
		to `"bar"` (the most common shape for "top/best X" sourcing questions)
		when no keyword matches.
	:rtype: str
	"""
	question_lower = question.lower()
	for keywords, chart_type in _KEYWORD_TO_CHART_TYPE:
		if any(keyword in question_lower for keyword in keywords):
			return chart_type
	return "bar"


def _select_columns(df: pd.DataFrame, metric_col: str | None) -> tuple[list[str], list[str]]:
	"""Pick the numeric/categorical columns `build_chart` renders from.

	:param df: The dataframe to chart.
	:type df: pd.DataFrame
	:param metric_col: Preferred numeric column for the value axis, if
		present — moved to the front of the numeric column list when it
		names a numeric column actually present in `df` (normally the query
		spec's `sort_by`, i.e. the column the question is actually
		ranking/scoring by, rather than an incidental extra numeric field).
	:type metric_col: str | None
	:return: `(numeric_cols, categorical_cols)`.
	:rtype: tuple[list[str], list[str]]
	"""
	numeric_cols = df.select_dtypes(include="number").columns.tolist()
	categorical_cols = df.select_dtypes(exclude="number").columns.tolist()
	if metric_col in numeric_cols:
		numeric_cols = [metric_col] + [c for c in numeric_cols if c != metric_col]
	return numeric_cols, categorical_cols


def build_histogram_option(df: pd.DataFrame, numeric_col: str, title: str) -> dict:
	"""Build an ECharts bar-chart option approximating a histogram.

	ECharts has no built-in binning, unlike Plotly's `px.histogram` — bins
	are computed with `numpy.histogram` (30 bins, matching the project's
	previous `nbins=30`) and rendered as a `bar` series over the bin ranges.

	:param df: The dataframe to chart.
	:type df: pd.DataFrame
	:param numeric_col: The numeric column to bin.
	:type numeric_col: str
	:param title: Chart title.
	:type title: str
	:return: An ECharts `option` dict.
	:rtype: dict
	"""
	counts, edges = np.histogram(df[numeric_col].dropna(), bins=30)
	labels = [f"{edges[i]:.1f}–{edges[i + 1]:.1f}" for i in range(len(edges) - 1)]
	return {
		"title": {"text": title},
		"color": SERIES_COLORS,
		"tooltip": {},
		"xAxis": {"type": "category", "data": labels, "name": numeric_col},
		"yAxis": {"type": "value", "name": "count"},
		"series": [{"type": "bar", "data": counts.tolist()}],
	}


def build_bar_option(
	df: pd.DataFrame, category_col: str, value_col: str, title: str, horizontal: bool = False
) -> dict:
	"""Build an ECharts bar-chart option.

	:param df: The dataframe to chart.
	:type df: pd.DataFrame
	:param category_col: Column for the category axis.
	:type category_col: str
	:param value_col: Column for the value axis.
	:type value_col: str
	:param title: Chart title.
	:type title: str
	:param horizontal: If True, categories go on the y-axis and values on
		the x-axis (used by "top N" style charts, matching the project's
		previous `orientation="h"` Plotly bar charts).
	:type horizontal: bool
	:return: An ECharts `option` dict.
	:rtype: dict
	"""
	category_axis = {"type": "category", "data": df[category_col].tolist(), "name": category_col}
	value_axis = {"type": "value", "name": value_col}
	series = [{"type": "bar", "data": df[value_col].tolist()}]
	base = {"title": {"text": title}, "color": SERIES_COLORS, "tooltip": {}, "series": series}
	if horizontal:
		return {**base, "xAxis": value_axis, "yAxis": category_axis}
	return {**base, "xAxis": category_axis, "yAxis": value_axis}


def build_chart(
	df: pd.DataFrame, chart_type: str, title: str = "", metric_col: str | None = None
) -> dict | None:
	"""Build an ECharts option dict from a result dataframe for the given chart type.

	Returns `None` (rather than raising) whenever the dataframe doesn't have
	the columns a chart type needs — the caller falls back to a plain table.

	:param df: The dataframe to chart (typically the NL search result).
	:type df: pd.DataFrame
	:param chart_type: One of `CHART_TYPES`.
	:type chart_type: str
	:param title: Chart title.
	:type title: str
	:param metric_col: Preferred numeric column for the value axis, if present.
	:type metric_col: str | None
	:return: An ECharts `option` dict (pass to `streamlit_echarts.st_echarts`),
		or `None` if no suitable chart could be built.
	:rtype: dict | None
	"""
	if chart_type not in CHART_TYPES or chart_type in ("none", "auto"):
		return None
	if df is None or df.empty:
		return None

	numeric_cols, categorical_cols = _select_columns(df, metric_col)

	if chart_type == "histogram":
		if not numeric_cols:
			return None
		return build_histogram_option(df, numeric_cols[0], title)

	if chart_type == "bar":
		if not categorical_cols or not numeric_cols:
			return None
		return build_bar_option(df, categorical_cols[0], numeric_cols[0], title)

	return None
