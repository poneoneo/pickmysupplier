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

import textwrap

import numpy as np
import pandas as pd
from loguru import logger

CHART_TYPES = ("none", "auto", "histogram", "bar", "box", "scatter", "map")

# Matches the dark reference design's chart series colors (blue/red/pink).
SERIES_COLORS = ["#5b8ff9", "#e8524c", "#f6a5c0"]

# This project's `country_name` field is French, lowercase (see
# `utils_scrapping.country_name`, e.g. "chine") — the world GeoJSON used by
# `build_map_option` (sourced from Apache ECharts' own map examples,
# `sourcing_intel_cli/world_map.json`) names regions in English (e.g.
# "China"). Deliberately a targeted list of common manufacturing/exporting
# nations, not all ~195 countries, since that's the realistic range of
# supplier countries a B2B sourcing marketplace actually returns — a
# country not in this table is silently skipped on the map rather than
# raising (see `build_map_option`), consistent with this project's general
# "skip what can't be rendered, keep the rest" policy. Note some real,
# valid values (e.g. "hong-kong", "taïwan") have no separate region in this
# particular world map and can never appear here, regardless of scope.
_FRENCH_TO_ENGLISH_COUNTRY = {
	"chine": "China",
	"inde": "India",
	"états-unis": "United States",
	"viet nam": "Vietnam",
	"allemagne": "Germany",
	"turquie": "Turkey",
	"pakistan": "Pakistan",
	"république de corée": "Korea",
	"italie": "Italy",
	"bangladesh": "Bangladesh",
	"espagne": "Spain",
	"népal": "Nepal",
	"france": "France",
	"royaume-uni": "United Kingdom",
	"japon": "Japan",
	"thaïlande": "Thailand",
	"indonésie": "Indonesia",
	"malaisie": "Malaysia",
	"philippines": "Philippines",
	"brésil": "Brazil",
	"mexique": "Mexico",
	"canada": "Canada",
	"australie": "Australia",
	"pays-bas": "Netherlands",
	"belgique": "Belgium",
	"pologne": "Poland",
	"portugal": "Portugal",
	"fédération de russie": "Russia",
	"égypte": "Egypt",
	"afrique du sud": "South Africa",
	"émirats arabes unis": "United Arab Emirates",
	"arabie saoudite": "Saudi Arabia",
	"singapour": "Singapore",
	"sri lanka": "Sri Lanka",
	"cambodge": "Cambodia",
	"myanmar": "Myanmar",
	"suède": "Sweden",
	"suisse": "Switzerland",
	"république tchèque": "Czech Rep.",
	"autriche": "Austria",
	"danemark": "Denmark",
	"finlande": "Finland",
	"norvège": "Norway",
	"grèce": "Greece",
	"irlande": "Ireland",
	"roumanie": "Romania",
	"hongrie": "Hungary",
	"ukraine": "Ukraine",
	"kazakhstan": "Kazakhstan",
	"israël": "Israel",
	"qatar": "Qatar",
	"koweït": "Kuwait",
	"jordanie": "Jordan",
	"nouvelle-zélande": "New Zealand",
	"argentine": "Argentina",
	"chili": "Chile",
	"colombie": "Colombia",
	"pérou": "Peru",
	"nigéria": "Nigeria",
	"kenya": "Kenya",
	"maroc": "Morocco",
	"tunisie": "Tunisia",
	"algérie": "Algeria",
	"république démocratique populaire lao": "Lao PDR",
	"mongolie": "Mongolia",
}


def _sanitize_for_json(values: list) -> list:
	"""Replace NaN with None so `st_echarts` can safely `json.dumps` the option.

	`st_echarts` serializes option dicts with plain `json.dumps`, which
	emits a bare `NaN` literal that the frontend's `JSON.parse` rejects —
	a legacy/degenerate database with null numeric fields would otherwise
	break the chart instead of just omitting a point.

	:param values: Numbers (or nested lists of numbers, e.g. `[[x, y], ...]`
		for scatter, or `[min, q1, median, q3, max]` per category for boxplot).
	:type values: list
	:return: The same structure with any float NaN replaced by `None`.
	:rtype: list
	"""
	def _clean(v):
		if isinstance(v, list):
			return [_clean(x) for x in v]
		if isinstance(v, float) and v != v:  # NaN != NaN
			return None
		return v
	return _clean(values)


def _wrap_title(text: str, width: int = 55) -> str:
	"""Break a long chart title into multiple lines at word boundaries.

	ECharts never wraps `title.text` on its own — a long NL question used
	as a chart title otherwise overflows the container and gets hard-clipped
	mid-word (confirmed via a real screenshot: "...fournisseurs ? (I").
	`textwrap` breaks it into full lines (never inside a word) at the
	nearest space before `width` characters, joined with `\n`, which
	ECharts' title component renders as genuine line breaks.

	:param text: The raw title text.
	:type text: str
	:param width: Max characters per line before wrapping.
	:type width: int
	:return: `text`, possibly with `\n` inserted between wrapped lines.
	:rtype: str
	"""
	return "\n".join(textwrap.wrap(text, width=width)) if text else text


def _base_option(title: str) -> dict:
	"""Shared option keys every chart type needs.

	`grid.containLabel` is the key fix here: without it, ECharts sizes the
	plotting grid to the axis lines only and lets the axis name/labels
	overflow past the container edge — which is exactly what was clipping
	axis titles like `"supplier_name"` down to `"supplier_na"` on Bar/Box/
	Scatter charts. With `containLabel: True`, ECharts reserves space for
	axis names/labels inside the grid so nothing gets cut off.

	:param title: Chart title.
	:type title: str
	:return: The option keys common to every `build_*_option` function.
	:rtype: dict
	"""
	return {
		"title": {"text": _wrap_title(title)},
		"color": SERIES_COLORS,
		"backgroundColor": "transparent",
		"tooltip": {},
		"grid": {"containLabel": True},
		# `saveAsImage` is a one-click PNG export of the chart (the
		# "screenshot" a fixed 420px-tall div otherwise has no way to
		# produce); `dataZoom`, in the toolbox and as its own component,
		# lets a visitor zoom in with the mouse wheel or the slider handles
		# to make a crowded chart's data effectively "bigger", and zoom
		# back out — no custom JS needed, this is all built into ECharts.
		"toolbox": {
			"feature": {
				"saveAsImage": {"title": "Télécharger en image"},
				"dataZoom": {"title": {"zoom": "Zoomer", "back": "Réinitialiser le zoom"}},
				"restore": {"title": "Réinitialiser"},
			}
		},
		"dataZoom": [{"type": "inside"}, {"type": "slider"}],
	}


# ECharts hides category-axis labels it estimates won't fit by default
# (axisLabel.interval="auto") instead of rotating them — `interval: 0`
# forces every label to render, `rotate` gives long names room to avoid
# overlapping.
_FULL_CATEGORY_LABELS = {"interval": 0, "rotate": 30}

# ECharts' default `nameLocation` for a value axis is "end" — for a y-axis
# that puts the axis name at the *top* of the axis, the same corner as
# title/subtext, so long subtitles visually collide with it. "middle" +
# `nameRotate: 90` renders it as a conventional vertical axis label running
# down the left side instead, which can't collide regardless of title length.
_VERTICAL_AXIS_NAME = {"nameLocation": "middle", "nameGap": 40, "nameRotate": 90}

# Same problem as _VERTICAL_AXIS_NAME, but for the x-axis: ECharts' default
# nameLocation="end" puts the name at the axis's right end, which overflows
# the container exactly the way the y-axis name did before that fix
# (confirmed via a real screenshot: "product_score" rendered as
# "product_scc"). "middle" centers it below the axis instead — the
# conventional place for an x-axis title, and it can't collide with
# anything at the edge.
_CENTERED_X_AXIS_NAME = {"nameLocation": "middle", "nameGap": 30}


def _describe_correlation(rho: float) -> str:
	"""Turn a Spearman rank correlation coefficient into a short French verdict.

	Spearman rather than Pearson: this chart typically plots a handful of
	bounded rating/score columns (0–5), where a couple of outlier points
	can give Pearson's linear fit disproportionate leverage on the reported
	number — confirmed on a real question ("score du produit" vs "score de
	service du fournisseur"), where Pearson's r (0.87) was pulled up by a
	few extreme low-score points relative to the dense high-score cluster.
	Spearman only looks at rank order, so a single outlier can't dominate
	it the same way, regardless of the underlying distribution's shape.

	:param rho: Spearman correlation coefficient, in `[-1, 1]`.
	:type rho: float
	:return: e.g. `"Corrélation (Spearman) : positive forte (ρ = 0.85, ρ² = 72%)"`,
		or `"Pas de corrélation notable (Spearman, ρ = 0.05)"` below the
		negligible threshold (`|rho| < 0.2`).
	:rtype: str
	"""
	abs_rho = abs(rho)
	if abs_rho < 0.2:
		return f"Pas de corrélation notable (Spearman, ρ = {rho:.2f})"
	if abs_rho < 0.5:
		strength = "faible"
	elif abs_rho < 0.8:
		strength = "modérée"
	else:
		strength = "forte"
	sign = "positive" if rho > 0 else "négative"
	return f"Corrélation (Spearman) : {sign} {strength} (ρ = {rho:.2f}, ρ² = {rho**2:.0%})"


_KEYWORD_TO_CHART_TYPE = (
	(("distribution", "répartition", "repartition"), "histogram"),
	(("dispersion", "écart", "ecart", "boîte", "boite", "box plot", "spread"), "box"),
	(("corrélation", "correlation", " vs ", "relation entre", "relationship between"), "scatter"),
	(("top", "meilleur", "best", "classement", "compar", "ranking"), "bar"),
	# Placed after "compar"/"ranking" deliberately: a question like "compare
	# the average price by country" must still resolve to "bar", not "map" —
	# this tuple's order is checked top to bottom.
	(("carte", "map", "géographique", "quels pays", "which countries", "countries are"), "map"),
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
		**_base_option(title),
		"xAxis": {"type": "category", "data": labels, "name": numeric_col, **_CENTERED_X_AXIS_NAME},
		"yAxis": {"type": "value", "name": "count", **_VERTICAL_AXIS_NAME},
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
	# A bar represents one category — when the same category appears on
	# multiple rows (e.g. several products from the same country, as an NL
	# query like "compare le prix moyen par pays" returns: one row per
	# product, not one row per country), average `value_col` per category
	# instead of plotting one unreadable bar per raw row. `sort=False` keeps
	# categories in first-seen order rather than pandas' default
	# alphabetical grouping. This also drops a NaN category automatically
	# (`groupby`'s default `dropna=True`) — a NaN category can't be
	# sanitized into a meaningful bar label the way `_sanitize_for_json`
	# handles NaN *values* (-> None), since `st_echarts` serializes the
	# option with plain `json.dumps`, which would otherwise emit a bare,
	# invalid `NaN` token for the category axis data and crash ECharts'
	# JS-side rendering pipeline.
	df = df.groupby(category_col, sort=False, as_index=False)[value_col].mean()
	category_data = df[category_col].tolist()
	series = [{"type": "bar", "data": _sanitize_for_json(df[value_col].tolist())}]
	base = {**_base_option(title), "series": series}
	if horizontal:
		# The value axis is the x-axis here (not the y-axis, like the
		# non-horizontal branch below), so *it* gets the centered-name
		# treatment instead — the category axis keeps its default name
		# position, unaffected by this branch.
		category_axis = {
			"type": "category",
			"data": category_data,
			"name": category_col,
			"axisLabel": _FULL_CATEGORY_LABELS,
		}
		value_axis = {"type": "value", "name": value_col, **_CENTERED_X_AXIS_NAME}
		return {**base, "xAxis": value_axis, "yAxis": category_axis}
	category_axis = {
		"type": "category",
		"data": category_data,
		"name": category_col,
		"axisLabel": _FULL_CATEGORY_LABELS,
		**_CENTERED_X_AXIS_NAME,
	}
	value_axis = {"type": "value", "name": value_col, **_VERTICAL_AXIS_NAME}
	return {**base, "xAxis": category_axis, "yAxis": value_axis}


def build_box_option(df: pd.DataFrame, category_col: str, value_col: str, title: str) -> dict:
	"""Build an ECharts boxplot option.

	ECharts' `boxplot` series needs `[min, Q1, median, Q3, max]` already
	computed per category — unlike Plotly's `px.box`, there's no
	client-side stats helper available from Python, so quartiles are
	computed per group with `pandas.Series.quantile` before building the
	option.

	:param df: The dataframe to chart.
	:type df: pd.DataFrame
	:param category_col: Column to group by (the box-plot categories).
	:type category_col: str
	:param value_col: Numeric column the boxes summarize.
	:type value_col: str
	:param title: Chart title.
	:type title: str
	:return: An ECharts `option` dict.
	:rtype: dict
	"""
	categories = []
	box_data = []
	# groupby excludes NaN group keys by default (pandas' dropna=True
	# default), so — unlike build_bar_option — no explicit dropna is needed
	# here to keep a NaN category out of the axis data.
	for name, group in df.groupby(category_col)[value_col]:
		categories.append(str(name))
		box_data.append(_sanitize_for_json(group.quantile([0, 0.25, 0.5, 0.75, 1]).tolist()))
	return {
		**_base_option(title),
		"xAxis": {
			"type": "category",
			"data": categories,
			"name": category_col,
			"axisLabel": _FULL_CATEGORY_LABELS,
			**_CENTERED_X_AXIS_NAME,
		},
		"yAxis": {"type": "value", "name": value_col, **_VERTICAL_AXIS_NAME},
		"series": [{"type": "boxplot", "data": box_data}],
	}


def build_scatter_option(df: pd.DataFrame, x_col: str, y_col: str, title: str) -> dict:
	"""Build an ECharts scatter-chart option, with a linear trend line and
	Spearman correlation coefficient overlaid when the data supports one.

	The trend line (least-squares fit, `numpy.polyfit` degree 1) is computed
	on the raw values, so it's drawn in the same coordinate space as the
	actual points — ECharts itself has no built-in regression, and the
	`ecStat` plugin that would add one isn't available in the pinned
	`streamlit-echarts==0.4.0` (see requirements.txt). The line is rendered
	as a second, symbol-less `line` series spanning just the two endpoints.

	The *quoted* correlation statistic, however, is Spearman's rank
	correlation (ρ) rather than Pearson's r — computed by rank-transforming
	`x`/`y` first (`pandas.Series.rank()`) and feeding the ranks into the
	same `numpy.corrcoef` call, since Spearman's ρ is mathematically just
	Pearson's r computed on ranks. This matters because Pearson can be
	pulled around by a handful of outlier points relative to a dense
	cluster — confirmed on a real chart (product score vs. supplier
	service score) where Pearson reported a "strong" 0.87 driven largely by
	a few low-score outliers next to a tight high-score cluster. Spearman's
	rank-based measure isn't swayed by that the same way. The trend line
	itself is unaffected by this — only the number in the subtitle changes.
	It's shown as the chart's subtitle rather than embedded in the series,
	since ECharts has no native "regression stats" element to attach it to.

	:param df: The dataframe to chart.
	:type df: pd.DataFrame
	:param x_col: Column for the x-axis.
	:type x_col: str
	:param y_col: Column for the y-axis.
	:type y_col: str
	:param title: Chart title.
	:type title: str
	:return: An ECharts `option` dict.
	:rtype: dict
	"""
	series = [{"type": "scatter", "data": _sanitize_for_json(df[[x_col, y_col]].values.tolist())}]
	subtext = ""

	clean = df[[x_col, y_col]].dropna()
	# A trend line/correlation needs at least 2 points, and both columns
	# need more than one distinct value — a constant x (vertical line of
	# points) makes the slope undefined, and a constant y makes the
	# correlation coefficient a 0/0 division (numpy would return NaN with a
	# RuntimeWarning rather than raise, but showing "ρ = nan" isn't useful).
	if len(clean) >= 2 and clean[x_col].nunique() > 1 and clean[y_col].nunique() > 1:
		x = clean[x_col].to_numpy(dtype=float)
		y = clean[y_col].to_numpy(dtype=float)
		# Trend line: ordinary least squares on the raw values, so it lines
		# up visually with the actual plotted points.
		slope, intercept = np.polyfit(x, y, 1)
		x_min, x_max = float(x.min()), float(x.max())
		series.append(
			{
				"type": "line",
				"data": [
					[x_min, slope * x_min + intercept],
					[x_max, slope * x_max + intercept],
				],
				"showSymbol": False,
				"lineStyle": {"type": "dashed"},
				"tooltip": {"show": False},
			}
		)
		# Quoted statistic: Spearman's rho, computed on ranks — deliberately
		# independent of the trend line above (see the function docstring).
		x_ranks = clean[x_col].rank().to_numpy()
		y_ranks = clean[y_col].rank().to_numpy()
		rho = float(np.corrcoef(x_ranks, y_ranks)[0, 1])
		subtext = _describe_correlation(rho)

	return {
		**_base_option(title),
		"title": {"text": _wrap_title(title), "subtext": subtext},
		"xAxis": {"type": "value", "name": x_col, **_CENTERED_X_AXIS_NAME},
		"yAxis": {"type": "value", "name": y_col, **_VERTICAL_AXIS_NAME},
		"series": series,
	}


def build_map_option(df: pd.DataFrame, category_col: str, title: str) -> dict:
	"""Build an ECharts world-map option: count of rows per country.

	`category_col`'s values are looked up in `_FRENCH_TO_ENGLISH_COUNTRY`
	(this project's country names are French, the map's regions are named
	in English) — any value not found there is skipped, not raised, so an
	unrecognized or unsupported country never breaks the whole chart.

	:param df: The dataframe to chart.
	:type df: pd.DataFrame
	:param category_col: Column naming the country per row — normally this
		project's `country_name` field.
	:type category_col: str
	:param title: Chart title.
	:type title: str
	:return: An ECharts `option` dict. `series[0].map` references the
		`"world"` map by name — the caller must also register the matching
		GeoJSON via `streamlit_echarts.Map("world", geojson)` passed to
		`st_echarts(..., map=...)`, or the region names in `data` have
		nothing to resolve against and nothing renders.
	:rtype: dict
	"""
	counts = df[category_col].value_counts()
	data = []
	skipped = []
	for french_name, count in counts.items():
		english_name = _FRENCH_TO_ENGLISH_COUNTRY.get(str(french_name).strip().lower())
		if english_name is None:
			skipped.append(french_name)
			continue
		data.append({"name": english_name, "value": int(count)})
	if skipped:
		logger.warning(f"build_map_option: no map region for {skipped!r} — skipped, not plotted.")

	return {
		**_base_option(title),
		"tooltip": {"trigger": "item", "formatter": "{b}: {c}"},
		"visualMap": {
			"min": 0,
			"max": max((d["value"] for d in data), default=1),
			"left": "left",
			"top": "bottom",
			"text": ["Élevé", "Faible"],
			"calculable": True,
			"inRange": {"color": ["#151822", SERIES_COLORS[0]]},
		},
		"series": [{"type": "map", "map": "world", "roam": True, "data": data}],
	}


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

	if chart_type == "box":
		if not categorical_cols or not numeric_cols:
			return None
		return build_box_option(df, categorical_cols[0], numeric_cols[0], title)

	if chart_type == "scatter":
		if len(numeric_cols) < 2:
			return None
		return build_scatter_option(df, numeric_cols[0], numeric_cols[1], title)

	if chart_type == "map":
		if not categorical_cols:
			return None
		# Prefer a column actually named like a country (this project's
		# `country_name` field) over "just the first categorical column" —
		# a product/supplier name column would never match anything in
		# `_FRENCH_TO_ENGLISH_COUNTRY`, silently producing an empty map
		# even when a real country column is present elsewhere in `df`.
		country_col = next(
			(c for c in categorical_cols if "country" in c.lower()), categorical_cols[0]
		)
		return build_map_option(df, country_col, title)

	return None
