"""Natural-language search over the products/suppliers DataFrame via Groq.

Originally built on `datahorse` (asks an LLM to write and `exec()` arbitrary
pandas code). Dropped after live testing showed it unreliable with the small
model this project can afford (`llama-3.1-8b-instant`): the same question
produced a different, sometimes broken, result on every call — see
`project_nl_search_value_hints` / the chart-axis bug it caused.

Instead, the LLM is asked for a small structured JSON *query spec*
(filter/sort/limit/columns) via Groq's JSON mode, which `apply_query_spec`
then executes deterministically with plain pandas — no generated code is
ever run.
"""

from __future__ import annotations

import json

import pandas as pd
from groq import Groq

from . import GROQ_API_KEY

GROQ_MODEL = "llama-3.1-8b-instant"

_QUERY_SPEC_SYSTEM_PROMPT = """\
You translate a natural-language question about a pandas dataframe into a \
JSON query spec. Never write code, never answer the question yourself — \
output ONLY a JSON object with this exact shape:

{{"filters": [{{"column": "<col>", "op": "==|!=|>|>=|<|<=|in|contains", "value": <value>}}], \
"sort_by": "<col>|null", "ascending": true|false, "keep": "highest|lowest|null", \
"limit": <int>|null, "columns": ["<col>", ...]}}

Rules:
- Only use column names from the list below — never invent a column.
- "value" for a filter must be one of the exact values listed for that \
column below, when a list is given for it.
- "sort_by" should be the column the question is actually ranking/scoring by.
- "ascending" is ONLY the final display order the user asked for \
("croissant"/"ascending" -> true, "décroissant"/"descending" -> false), \
nothing else.
- "keep" is ONLY about which extreme of "sort_by" the question wants when \
"limit" narrows the results down: "highest" for top/best/most/greatest/ \
plus grand/meilleur-style questions, "lowest" for bottom/worst/least/ \
smallest/plus petit/pire-style questions, null if the question has no such \
notion (e.g. just "show 5 suppliers" with no best/worst framing).
- "ascending" and "keep" are independent — a question can ask for the \
HIGHEST values shown in ASCENDING order at the same time (e.g. "top 5 \
suppliers by score, ascending" -> sort_by="supplier_service_score", \
ascending=true, keep="highest", limit=5).
- "columns" lists the fields relevant to answering the question, in display \
order, with the field the question is really about listed first. When a \
product is being displayed by name, prefer "short_name" over \
"product_name" (short_name is a shorter, equally identifying version made \
for display) — use "product_name" itself only if the question needs exact \
text matching against it.
- "limit" is the number of rows requested (e.g. "top 5" -> 5), or null if \
the question doesn't ask for a specific count.
- Filters are combined with AND. To match several values of the same \
column (e.g. several countries), use ONE filter with op "in" and a list \
value — never add one "==" filter per value, that would require a single \
cell to equal several different values at once and match nothing.
- Omit a filter entirely rather than giving it a null/placeholder value.

Available columns (name: dtype):
{schema}

{hints}"""


def build_value_hints(df: pd.DataFrame, max_unique: int = 30) -> str:
	"""Build a hint string listing the real values of low-cardinality text columns.

	The model never sees actual cell values otherwise — only column names/
	dtypes — so without this it guesses a plausible-looking filter value
	(e.g. `"China"`) instead of matching what's really stored (e.g.
	`"chine"`, lowercase French — see `utils_scrapping.country_name`).

	:param df: The dataframe about to be queried.
	:param max_unique: Skip columns with more unique values than this — free
		text columns (product/supplier names) aren't useful to enumerate.
	:return: A hint string, or `""` if no column qualifies.
	"""
	hints = []
	for col in df.select_dtypes(exclude="number").columns:
		uniques = df[col].dropna().unique()
		if 0 < len(uniques) <= max_unique:
			values = ", ".join(repr(v) for v in sorted(uniques))
			hints.append(f"- {col}: {values}")
	if not hints:
		return ""
	return (
		"Exact values present in these columns (only use these as filter "
		"values for their own column, never for another column):\n" + "\n".join(hints)
	)


def build_query_spec(question: str, df: pd.DataFrame) -> dict:
	"""Ask Groq for a structured filter/sort/select spec answering `question`.

	:param question: The user's natural-language question.
	:param df: The dataframe the spec will later be applied to.
	:raises RuntimeError: If `GROQ_API_KEY` isn't set, or the model's
		response isn't valid JSON.
	:return: A dict with keys `filters`, `sort_by`, `ascending`, `limit`,
		`limit_from`, `columns` (see `apply_query_spec`).
	"""
	if not GROQ_API_KEY:
		raise RuntimeError(
			"GROQ_API_KEY n'est pas défini — la recherche en langage naturel est indisponible."
		)
	schema = "\n".join(f"- {col}: {dtype}" for col, dtype in df.dtypes.items())
	system_prompt = _QUERY_SPEC_SYSTEM_PROMPT.format(schema=schema, hints=build_value_hints(df))

	client = Groq(api_key=GROQ_API_KEY)
	completion = client.chat.completions.create(
		messages=[
			{"role": "system", "content": system_prompt},
			{"role": "user", "content": question},
		],
		model=GROQ_MODEL,
		response_format={"type": "json_object"},
		temperature=0,
	)
	content = completion.choices[0].message.content
	try:
		return json.loads(content)
	except (json.JSONDecodeError, TypeError) as e:
		raise RuntimeError(f"Réponse du modèle non exploitable : {e}") from e


_FILTER_OPS = {
	"==": lambda series, value: series == value,
	"!=": lambda series, value: series != value,
	">": lambda series, value: series > value,
	">=": lambda series, value: series >= value,
	"<": lambda series, value: series < value,
	"<=": lambda series, value: series <= value,
	"in": lambda series, value: series.isin(value if isinstance(value, list) else [value]),
	"contains": lambda series, value: series.astype(str).str.contains(
		str(value), case=False, na=False
	),
}


def _merge_same_column_equality_filters(filters: list[dict]) -> list[dict]:
	"""Merge multiple `==` filters on the same column into one `in` filter.

	A cell can never equal two different values at once, so ANDing several
	`==` filters on the same column sequentially always yields zero rows.
	The model sometimes emits exactly that (e.g. one filter per country
	instead of a single `in` filter) when the real intent is "any of
	these" — OR, not AND.

	:param filters: The spec's raw `filters` list (already dict-filtered).
	:return: An equivalent filter list with same-column `==` filters merged.
	"""
	from collections import defaultdict

	equality_values_by_column: dict[str, list] = defaultdict(list)
	other_filters = []
	for f in filters:
		if f.get("op") == "==":
			equality_values_by_column[f.get("column")].append(f.get("value"))
		else:
			other_filters.append(f)

	merged = [
		{"column": col, "op": "==", "value": values[0]}
		if len(values) == 1
		else {"column": col, "op": "in", "value": values}
		for col, values in equality_values_by_column.items()
	]
	return merged + other_filters


def apply_query_spec(df: pd.DataFrame, spec: dict) -> pd.DataFrame:
	"""Deterministically apply a query spec (filter/sort/limit/columns) to `df`.

	Never raises on a malformed spec — unknown columns, ops, or a spec that
	isn't even a dict are skipped/ignored rather than blowing up, since the
	spec comes from an LLM and partial results are better than a crash.

	:param df: The dataframe to query.
	:param spec: A dict as produced by `build_query_spec`.
	:return: The filtered/sorted/limited/column-selected dataframe.
	"""
	result = df
	if not isinstance(spec, dict):
		return result

	raw_filters = [f for f in (spec.get("filters") or []) if isinstance(f, dict)]
	for f in _merge_same_column_equality_filters(raw_filters):
		col, op, value = f.get("column"), f.get("op"), f.get("value")
		# A null value (the model sometimes emits a redundant/empty filter)
		# isn't meaningful for any of our ops — comparing a numeric column
		# to None doesn't raise, it silently matches nothing, so this must
		# be checked explicitly rather than relying on try/except below.
		if col not in result.columns or op not in _FILTER_OPS or value is None:
			continue
		try:
			result = result[_FILTER_OPS[op](result[col], value)]
		except (TypeError, ValueError):
			continue

	# `df` is a Product<->Supplier join (one row per product), so any
	# supplier-level answer naturally repeats a supplier once per product it
	# sells. Once narrowed to just the columns being displayed, those
	# repeats become fully identical rows — showing the same supplier twice
	# adds no information, and Plotly's bar charts stack repeated
	# x-categories within one trace, silently inflating that supplier's bar
	# height. Deduped here (subset = the eventual display columns, computed
	# before actually trimming to them) rather than at the end, so "top 5"
	# below counts 5 *unique* rows, not 5 rows that might collapse to fewer.
	columns = spec.get("columns")
	valid_columns = [c for c in columns if c in result.columns] if isinstance(columns, list) else []
	result = result.drop_duplicates(subset=valid_columns or None)

	sort_by = spec.get("sort_by")
	ascending = bool(spec.get("ascending", True))
	if sort_by in result.columns:
		result = result.sort_values(by=sort_by, ascending=ascending)

	limit = spec.get("limit")
	if isinstance(limit, int) and limit > 0:
		# "ascending" (display order) and "keep" (which extreme to narrow
		# down to) are independent — e.g. "top 5, ascending" wants the 5
		# HIGHEST values displayed lowest-to-highest. Working that out from
		# a single derived direction was unreliable with this small model
		# (it kept conflating the two), so each is asked for literally and
		# we compute which end of the sort to take from ourselves.
		keep = spec.get("keep")
		if keep in ("highest", "lowest"):
			take_from_end = (keep == "highest") == ascending
		else:
			take_from_end = False
		result = result.tail(limit) if take_from_end else result.head(limit)

	if valid_columns:
		result = result[valid_columns]

	return result.reset_index(drop=True)
