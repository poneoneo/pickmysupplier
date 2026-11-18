"""What a dataset actually contains, so charts and suggestions stay honest.

A live scrape doesn't fill every column the way the demo dataset does: the
site's search API has no per-offer "verified" badge (stored as "unknown"),
never exposes the five boolean flags (stored as False since 2026-08), and
leaves some ratings blank (stored as 0.0). Read as real values, those would
skew the analysis — a blank rating counted as 0/5 drags every average down,
and a chart of "Trade Assurance coverage" would show 0% everywhere.

`mark_missing_values` turns those placeholders into real missing values
(NaN/None, which pandas and the charts skip), `unavailable_columns` lists
what a dataset can't answer at all, and `example_questions` /
`unavailable_fields_mentioned` keep the Explorer page's suggestions and
searches to what can really be queried.
"""

from __future__ import annotations

from collections import Counter

import pandas as pd

# Ratings out of 5: 0 is never a real rating, it's a blank field.
RATING_COLUMNS = ("product_score", "review_score", "shipping_time_score", "supplier_service_score")

# True/False flags no current scrape source provides — always False there.
FLAG_COLUMNS = (
	"trade_product",
	"alibaba_guranteed",
	"is_full_promotion",
	"is_customizable",
	"is_instant_order",
)

UNKNOWN_VERIFICATION = {"unknown", ""}

FIELD_LABELS = {
	"verification_mode": "supplier verification status",
	"trade_product": "Trade Assurance",
	"alibaba_guranteed": "marketplace guarantee",
	"is_full_promotion": "promotions",
	"is_customizable": "customization",
	"is_instant_order": "instant order",
	"certifications": "certifications",
	"product_score": "product rating",
	"review_score": "review rating",
	"shipping_time_score": "shipping rating",
	"supplier_service_score": "supplier service rating",
}

# Words that show a question relies on a field (lowercase substrings).
_FIELD_KEYWORDS = {
	"verification_mode": ("verified", "verification"),
	"trade_product": ("trade assurance", "trade_product"),
	"alibaba_guranteed": ("guarantee",),
	"is_full_promotion": ("promotion",),
	"is_customizable": ("customiz", "customis"),
	"is_instant_order": ("instant order", "instant_order"),
	"certifications": ("certif",),
	"product_score": ("product score", "product_score", "product rating"),
	"review_score": ("review score", "review_score"),
	"shipping_time_score": ("shipping", "delivery"),
	"supplier_service_score": ("service score", "service rating", "supplier_service"),
}

# (question template, columns it needs, chart "Auto" picks for it). The
# chart is checked against `chart_builder.suggest_chart_type` in the tests;
# "Table" marks list questions where the user must pick "Table only".
EXAMPLE_QUESTIONS: tuple[tuple[str, frozenset[str], str], ...] = (
	("Which 5 suppliers have the best supplier_service_score?", frozenset({"supplier_service_score"}), "Bar"),
	("What is the distribution of minimum prices?", frozenset(), "Histogram"),
	("What is the spread of product_score by supplier country?", frozenset({"product_score"}), "Box plot"),
	("Is there a correlation between product_score and min_price?", frozenset({"product_score"}), "Scatter"),
	("Compare the average product price by supplier country.", frozenset(), "Bar"),
	("Compare the average shipping_time_score by supplier country.", frozenset({"shipping_time_score"}), "Bar"),
	("Is there a correlation between review_count and review_score?", frozenset({"review_score"}), "Scatter"),
	("Which 10 products have sold the most units?", frozenset(), "Bar"),
	("What is the distribution of MOQ (minimum order quantity)?", frozenset(), "Histogram"),
	("Which countries are represented among the suppliers?", frozenset(), "World map"),
	(
		"List suppliers in {country} with at least 5 years as a Gold Supplier, sorted by minimum price.",
		frozenset(),
		"Table",
	),
	("List verified suppliers in {country}, sorted by minimum price.", frozenset({"verification_mode"}), "Table"),
	("List products with {certification} certification, sorted by minimum price.", frozenset({"certifications"}), "Table"),
	("List products covered by Trade Assurance, sorted by minimum price.", frozenset({"trade_product"}), "Table"),
)


def mark_missing_values(df: pd.DataFrame) -> pd.DataFrame:
	"""Turn placeholder values into real missing values.

	Ratings of 0 (a blank field on the site) become NaN, and an "unknown"
	verification status becomes None — pandas aggregations and the charts
	skip both instead of counting them. Counts (reviews, units sold) are left
	alone: 0 is a real count there.

	:param df: Products joined to suppliers, as loaded by the app.
	:type df: pd.DataFrame
	:return: A copy of `df` with placeholders replaced.
	:rtype: pd.DataFrame
	"""
	df = df.copy()
	for col in RATING_COLUMNS:
		if col in df.columns:
			df[col] = pd.to_numeric(df[col], errors="coerce")
			df.loc[df[col] <= 0, col] = float("nan")
	if "verification_mode" in df.columns:
		unknown = df["verification_mode"].fillna("").astype(str).str.strip().str.lower().isin(UNKNOWN_VERIFICATION)
		df["verification_mode"] = df["verification_mode"].astype(object).where(~unknown, None)
	return df


def unavailable_columns(df: pd.DataFrame) -> list[str]:
	"""Columns this dataset can't answer anything about.

	A rating or the verification status is unavailable when every value is
	missing; a flag when no row is True (no current scrape source provides
	any of them, so all-False means "not collected", not "none of them");
	certifications when every product has none listed.

	:param df: Products joined to suppliers, after `mark_missing_values`.
	:type df: pd.DataFrame
	:return: The unavailable columns, in a stable order.
	:rtype: list[str]
	"""
	unavailable = []
	for col in FIELD_LABELS:
		if col not in df.columns:
			continue
		values = df[col]
		if col in FLAG_COLUMNS:
			empty = not values.fillna(0).astype(bool).any()
		elif col == "certifications":
			empty = values.fillna("").astype(str).str.strip().eq("").all()
		else:
			empty = values.isna().all()
		if empty:
			unavailable.append(col)
	return unavailable


def missing_share(df: pd.DataFrame) -> dict[str, float]:
	"""Share of rows with a blank rating, for ratings that are only partly blank.

	:param df: Products joined to suppliers, after `mark_missing_values`.
	:type df: pd.DataFrame
	:return: Column -> share of missing values (strictly between 0 and 1).
	:rtype: dict[str, float]
	"""
	shares = {}
	for col in RATING_COLUMNS:
		if col in df.columns and len(df):
			share = float(df[col].isna().mean())
			if 0 < share < 1:
				shares[col] = share
	return shares


def _most_common_certification(df: pd.DataFrame) -> str:
	"""The certification name listed on the most products ("CE" if none)."""
	if "certifications" not in df.columns:
		return "CE"
	names = Counter(
		name.strip()
		for value in df["certifications"].dropna().astype(str)
		for name in value.split(",")
		if name.strip()
	)
	return names.most_common(1)[0][0] if names else "CE"


def example_questions(df: pd.DataFrame, unavailable: list[str]) -> list[tuple[str, str]]:
	"""Example questions this dataset can really answer, with their chart.

	:param df: Products joined to suppliers, after `mark_missing_values`.
	:type df: pd.DataFrame
	:param unavailable: Output of `unavailable_columns(df)`.
	:type unavailable: list[str]
	:return: `(question, chart label)` pairs, filled with values present in
		the data (most common country and certification).
	:rtype: list[tuple[str, str]]
	"""
	countries = df["country_name"].dropna() if "country_name" in df.columns else pd.Series(dtype=str)
	country = countries.value_counts().index[0] if not countries.empty else "China"
	certification = _most_common_certification(df)
	return [
		(template.format(country=country, certification=certification), chart)
		for template, required, chart in EXAMPLE_QUESTIONS
		if not required & set(unavailable)
	]


def unavailable_fields_mentioned(query: str, unavailable: list[str]) -> list[str]:
	"""Unavailable fields a natural-language question seems to rely on.

	The search silently ignores a filter on a column it can't use, so
	"verified suppliers" on a dataset without verification data would
	return every supplier as if they were all verified. The app warns
	instead.

	:param query: The visitor's question.
	:type query: str
	:param unavailable: Output of `unavailable_columns`.
	:type unavailable: list[str]
	:return: The unavailable columns whose keywords appear in `query`.
	:rtype: list[str]
	"""
	text = query.lower()
	return [
		col for col in unavailable if any(word in text for word in _FIELD_KEYWORDS.get(col, ()))
	]
