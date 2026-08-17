"""Deterministic chart-type selection and Plotly figure construction for the
natural-language search results (see `nl_search.py` for how the result
dataframe itself is produced — deterministically, not LLM-generated code).

Chart selection stays outside the LLM entirely: either the user picks a
chart type explicitly, or `suggest_chart_type` maps the question's wording
to one of a fixed set of chart types, and `build_chart` renders it from
whatever columns the result dataframe actually has.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

CHART_TYPES = ("none", "auto", "histogram", "bar", "box", "scatter")

_KEYWORD_TO_CHART_TYPE = (
	(("distribution", "répartition", "repartition"), "histogram"),
	(("dispersion", "écart", "ecart", "boîte", "boite"), "box"),
	(("corrélation", "correlation", " vs ", "relation entre"), "scatter"),
	(("top", "meilleur", "classement", "compar"), "bar"),
)


def suggest_chart_type(question: str) -> str:
	"""Map a natural-language question to a chart type using keyword matching.

	:param question: The user's natural-language question.
	:return: One of `"histogram"`, `"bar"`, `"box"`, `"scatter"` — falls back
		to `"bar"` (the most common shape for "top/best X" sourcing questions)
		when no keyword matches.
	"""
	question_lower = question.lower()
	for keywords, chart_type in _KEYWORD_TO_CHART_TYPE:
		if any(keyword in question_lower for keyword in keywords):
			return chart_type
	return "bar"


def build_chart(
	df: pd.DataFrame, chart_type: str, title: str = "", metric_col: str | None = None
) -> go.Figure | None:
	"""Build a Plotly figure from a result dataframe for the given chart type.

	Picks columns automatically: `metric_col` (when it names a numeric
	column actually present) is used as the value axis in preference to
	"the first numeric column" — this is normally the query spec's
	`sort_by`, i.e. the column the question is actually ranking/scoring by,
	rather than an incidental extra numeric field. The label axis is the
	first non-numeric column in `df`'s column order (the query spec already
	puts the most relevant column first there). Returns `None` (rather than
	raising) whenever the dataframe doesn't have the columns a chart type
	needs — the caller falls back to a plain table.

	:param df: The dataframe to chart (typically the NL search result).
	:param chart_type: One of `CHART_TYPES`.
	:param title: Chart title.
	:param metric_col: Preferred numeric column for the value axis, if present.
	:return: A Plotly figure, or `None` if no suitable chart could be built.
	"""
	if chart_type not in CHART_TYPES or chart_type in ("none", "auto"):
		return None
	if df is None or df.empty:
		return None

	numeric_cols = df.select_dtypes(include="number").columns.tolist()
	categorical_cols = df.select_dtypes(exclude="number").columns.tolist()

	if metric_col in numeric_cols:
		numeric_cols = [metric_col] + [c for c in numeric_cols if c != metric_col]

	if chart_type == "histogram":
		if not numeric_cols:
			return None
		return px.histogram(df, x=numeric_cols[0], nbins=30, title=title)

	if chart_type == "bar":
		if not categorical_cols or not numeric_cols:
			return None
		return px.bar(df, x=categorical_cols[0], y=numeric_cols[0], title=title)

	if chart_type == "box":
		if not categorical_cols or not numeric_cols:
			return None
		return px.box(df, x=categorical_cols[0], y=numeric_cols[0], title=title)

	if chart_type == "scatter":
		if len(numeric_cols) < 2:
			return None
		return px.scatter(df, x=numeric_cols[0], y=numeric_cols[1], title=title)

	return None
