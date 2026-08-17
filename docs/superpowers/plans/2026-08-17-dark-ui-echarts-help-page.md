# Dark Redesign, ECharts Migration, Aide Page, BYO ScrapingBee Key Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the Streamlit app into a dark-themed, multi-page navigation (Accueil/Explorer/Scraper/Aide), replace all Plotly charts with ECharts, and let visitors supply their own ScrapingBee API key with a clear banner when the shared demo key runs out of credits.

**Architecture:** `app.py` moves from a single-page sidebar-plus-tabs layout to `st.navigation`/`st.Page` with four page functions defined in the same file (no `pages/` directory — `app.py` stays the single entry point). `chart_builder.py`'s `build_chart` changes its return type from a Plotly `go.Figure` to an ECharts `option` dict, rendered via `streamlit-echarts`'s `st_echarts`. `ScrapingBeeProxyProvider` gains an optional `api_key` override and raises a specific `ScrapingBeeQuotaExceeded` exception on HTTP 429, caught in the UI to flip a `st.session_state` flag that drives a persistent banner.

**Tech Stack:** Streamlit ≥1.36 (`st.navigation`/`st.Page`), `streamlit-echarts` (ECharts option dicts), `numpy` (histogram binning, boxplot quartiles), existing pandas/SQLModel/loguru/Groq stack unchanged.

**Spec:** `docs/superpowers/specs/2026-08-17-dark-ui-echarts-help-page-design.md`

## Global Constraints

- `streamlit>=1.36` (was `>=1.35`) — floor for `st.navigation`/`st.Page`.
- New dependencies: `streamlit-echarts>=0.7`, `numpy>=1.24`.
- Every chart renders via `streamlit_echarts.st_echarts` — no `st.plotly_chart` or `import plotly` anywhere in the final state.
- No BrightData BYO-key flow — the `api_key` override is ScrapingBee-only.
- No real browser cookies for the quota-exhausted signal — `st.session_state` only, resets per browser tab.
- `app.py` stays the single Streamlit entry point — page functions live in `app.py`, no `pages/` directory.
- Indentation: tabs, not spaces (matches existing files). Sphinx-style docstrings (`:param:`, `:type:`, `:return:`, `:rtype:`) on every new function. Type hints on every function signature. `loguru.logger` for logging, never bare `print()` outside `app.py` (which uses Streamlit's own display primitives).
- Always run `python -m pytest` and `python -m ruff check .` — never bare `pytest`/`ruff` (package isn't installed with `pip install -e .`, so only `python -m` puts the repo root on `sys.path`).
- Commit after each task (or each clearly-separated sub-step within Task 3 and Task 5, noted inline below).

---

## Task 1: Add new dependencies

**Files:**
- Modify: `requirements.txt`

**Interfaces:**
- Produces: `streamlit-echarts` and `numpy` importable in the environment for Tasks 2–5.

- [ ] **Step 1: Edit `requirements.txt`**

Change:
```
streamlit>=1.35
plotly>=5.20
```
to:
```
streamlit>=1.36
streamlit-echarts>=0.7
numpy>=1.24
plotly>=5.20
```
(`plotly` stays for now — it's removed in Task 6 once nothing imports it anymore.)

- [ ] **Step 2: Install and verify**

Run: `python -m pip install -r requirements.txt`
Then verify the import works:
Run: `python -c "import streamlit_echarts; import numpy; print('ok')"`
Expected: prints `ok` with no `ModuleNotFoundError`.

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "chore: add streamlit-echarts and numpy dependencies"
```

---

## Task 2: ScrapingBee BYO key + quota-exceeded detection

**Files:**
- Modify: `sourcing_intel_cli/proxies_providers.py`
- Test: `tests/test_proxies_providers.py`

**Interfaces:**
- Produces:
  - `ScrapingBeeQuotaExceeded(RuntimeError)` — module-level exception class in `proxies_providers.py`.
  - `_resolve_scrapingbee_key(visitor_key: str | None, fallback_key: str) -> str`
  - `_fetch_via_scrapingbee(api_request, endpoint: str, api_key: str, url: str)` — returns a Playwright-style response object (`.ok`, `.status`, `.text()`); raises `ScrapingBeeQuotaExceeded` on HTTP 429.
  - `ScrapingBeeProxyProvider.sync_scraper(*, save_in: str, key_words: str, page_results: int, api_key: str | None = None) -> None` — new optional `api_key` param, falls back to `cls.SB_API_KEY` (the `.env` value) when not given.
- Consumes: nothing new — builds on the existing `TARGET_COUNTRY` constant already in this file.

### Step group A: `_resolve_scrapingbee_key`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_proxies_providers.py`:
```python
from sourcing_intel_cli.proxies_providers import _resolve_scrapingbee_key


class TestResolveScrapingbeeKey:
	def test_uses_visitor_key_when_provided(self):
		assert _resolve_scrapingbee_key("visitor-key", "owner-key") == "visitor-key"

	def test_falls_back_to_owner_key_when_visitor_key_is_none(self):
		assert _resolve_scrapingbee_key(None, "owner-key") == "owner-key"

	def test_falls_back_to_owner_key_when_visitor_key_is_empty_string(self):
		assert _resolve_scrapingbee_key("", "owner-key") == "owner-key"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_proxies_providers.py::TestResolveScrapingbeeKey -v`
Expected: FAIL with `ImportError: cannot import name '_resolve_scrapingbee_key'`.

- [ ] **Step 3: Implement**

In `sourcing_intel_cli/proxies_providers.py`, add near the top-level constants (after `TARGET_COUNTRY`, before `class BrightDataProxyProvider`):
```python
def _resolve_scrapingbee_key(visitor_key: str | None, fallback_key: str) -> str:
	"""Pick which ScrapingBee API key to use for a scrape.

	:param visitor_key: The key a visitor typed into the Scraper page's
		optional field, if any.
	:type visitor_key: str | None
	:param fallback_key: The owner's key from `.env` (`SCRAPINGBEE_API_KEY`).
	:type fallback_key: str
	:return: `visitor_key` if non-empty, else `fallback_key`.
	:rtype: str
	"""
	return visitor_key or fallback_key
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_proxies_providers.py::TestResolveScrapingbeeKey -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add sourcing_intel_cli/proxies_providers.py tests/test_proxies_providers.py
git commit -m "feat: resolve ScrapingBee key from visitor override or .env fallback"
```

### Step group B: `ScrapingBeeQuotaExceeded` + `_fetch_via_scrapingbee`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_proxies_providers.py`:
```python
import pytest

from sourcing_intel_cli.proxies_providers import (
	TARGET_COUNTRY,
	ScrapingBeeQuotaExceeded,
	_fetch_via_scrapingbee,
)


class _StubResponse:
	def __init__(self, status: int, text: str = ""):
		self.status = status
		self.ok = status < 400
		self._text = text

	def text(self):
		return self._text


class _StubAPIRequest:
	def __init__(self, response: _StubResponse):
		self._response = response
		self.last_params = None

	def get(self, url, params=None, timeout=None):
		self.last_params = params
		return self._response


class TestFetchViaScrapingbee:
	def test_uses_provided_api_key(self):
		stub = _StubAPIRequest(_StubResponse(200, "<html></html>"))
		_fetch_via_scrapingbee(stub, "https://endpoint.example", "my-key", "https://target.example")
		assert stub.last_params["api_key"] == "my-key"

	def test_pins_country_and_premium_proxy(self):
		stub = _StubAPIRequest(_StubResponse(200))
		_fetch_via_scrapingbee(stub, "https://endpoint.example", "my-key", "https://target.example")
		assert stub.last_params["country_code"] == TARGET_COUNTRY
		assert stub.last_params["premium_proxy"] == "true"

	def test_429_raises_quota_exceeded(self):
		stub = _StubAPIRequest(_StubResponse(429))
		with pytest.raises(ScrapingBeeQuotaExceeded):
			_fetch_via_scrapingbee(stub, "https://endpoint.example", "my-key", "https://target.example")

	def test_non_429_failure_returns_response_not_ok(self):
		stub = _StubAPIRequest(_StubResponse(500))
		response = _fetch_via_scrapingbee(stub, "https://endpoint.example", "my-key", "https://target.example")
		assert response.ok is False

	def test_success_returns_response_text(self):
		stub = _StubAPIRequest(_StubResponse(200, "<html>ok</html>"))
		response = _fetch_via_scrapingbee(stub, "https://endpoint.example", "my-key", "https://target.example")
		assert response.ok is True
		assert response.text() == "<html>ok</html>"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_proxies_providers.py::TestFetchViaScrapingbee -v`
Expected: FAIL with `ImportError: cannot import name 'ScrapingBeeQuotaExceeded'`.

- [ ] **Step 3: Implement**

In `sourcing_intel_cli/proxies_providers.py`, add right after `_resolve_scrapingbee_key`:
```python
class ScrapingBeeQuotaExceeded(RuntimeError):
	"""Raised when ScrapingBee reports the API key is out of credits (HTTP 429)."""


def _fetch_via_scrapingbee(api_request, endpoint: str, api_key: str, url: str):
	"""Fetch one page's HTML through the ScrapingBee REST API.

	Isolated from `ScrapingBeeProxyProvider.sync_scraper`'s Playwright
	setup/teardown so the api_key-resolution and quota-detection logic can
	be unit tested with a stubbed `api_request` (see
	`tests/test_proxies_providers.py`) instead of needing a real browser or
	network access.

	:param api_request: A Playwright `APIRequestContext` (or a stub exposing
		the same `.get(url, params=..., timeout=...)` -> response interface).
	:param endpoint: The ScrapingBee REST endpoint.
	:type endpoint: str
	:param api_key: The resolved ScrapingBee API key (visitor's own, or the
		owner's `.env` fallback — see `_resolve_scrapingbee_key`).
	:type api_key: str
	:param url: The target page URL to scrape.
	:type url: str
	:raises ScrapingBeeQuotaExceeded: If ScrapingBee reports HTTP 429
		(credits exhausted).
	:return: The response object (`.ok`, `.status`, `.text()`).
	"""
	response = api_request.get(
		endpoint,
		params={
			"api_key": api_key,
			"url": url,
			"render_js": "true",
			"premium_proxy": "true",
			"country_code": TARGET_COUNTRY,
		},
		timeout=0,
	)
	if response.status == 429:
		raise ScrapingBeeQuotaExceeded(
			"La clé ScrapingBee a épuisé son quota de crédits (HTTP 429)."
		)
	return response
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_proxies_providers.py::TestFetchViaScrapingbee -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add sourcing_intel_cli/proxies_providers.py tests/test_proxies_providers.py
git commit -m "feat: raise ScrapingBeeQuotaExceeded on HTTP 429 from ScrapingBee"
```

### Step group C: wire both into `ScrapingBeeProxyProvider.sync_scraper`

- [ ] **Step 1: Update `sync_scraper`'s signature and body**

In `sourcing_intel_cli/proxies_providers.py`, replace the whole `ScrapingBeeProxyProvider.sync_scraper` method with:
```python
	@classmethod
	def sync_scraper(
		cls, *, save_in: str, key_words: str, page_results: int, api_key: str | None = None
	) -> None:
		"""
		Initiates synchronous scraping via the ScrapingBee API based on the provided keywords.

		ScrapingBee renders the target page server-side (JS execution included) and returns
		the resulting HTML in the response body, so no local browser navigation is needed —
		Playwright's request context is used purely as an HTTP client.

		:param save_in: The directory to store the raw HTML files.
		:type save_in: str
		:param key_words: The search term(s) for finding products on Alibaba.
		:type key_words: str
		:param page_results: The number of pages to scrape.
		:type page_results: int
		:param api_key: A visitor-supplied ScrapingBee key to use instead of the
			owner's `SCRAPINGBEE_API_KEY` from `.env`, if provided.
		:type api_key: str | None
		:return: None
		:rtype: None
		:raises RuntimeError: If no API key is set (neither `api_key` nor the
			owner's `.env` key).
		:raises ScrapingBeeQuotaExceeded: If ScrapingBee reports the resolved
			key is out of credits (HTTP 429) — callers should catch this
			before the generic `RuntimeError` to show a specific "get your
			own free key" message.
		"""
		resolved_key = _resolve_scrapingbee_key(api_key, cls.SB_API_KEY)
		if resolved_key == "":
			rprint("[red]You need to set your  API key to use ScrapingBee proxies ... [/red]")
			raise RuntimeError("You need to set your ScrapingBee API key to use ScrapingBee proxies.")
		with Progress(
			SpinnerColumn(finished_text="[bold green]finished ✓[/bold green]"),
			*Progress.get_default_columns(),
			transient=True,
		) as progress:
			task = progress.add_task(
				"[green blink] Sync Scraping...",
				start=False,
			)
			playwright = sync_playwright().start()
			api_request = playwright.request.new_context()
			try:
				for url in urls_pusher(words=key_words, stop_at=page_results):
					logger.info(f"Loading page {url.split('page=')[1]} ... ")
					response = _fetch_via_scrapingbee(api_request, cls.ENDPOINT, resolved_key, url)
					if not response.ok:
						logger.warning(
							f"ScrapingBee request failed for page {url.split('page=')[1]} "
							f"(status {response.status}), skipping it."
						)
						continue
					logger.info(
						f"Returns the text representation of response body from page {url.split('page=')[1]} ... "
					)
					progress.start_task(task)
					html_content = response.text()
					progress.update(task, advance=100 / page_results)
					global HTML_PAGE_RESULT
					HTML_PAGE_RESULT.append(html_content)
					logger.info(f"Closing the page {url.split('page=')[1]} ... ")
			finally:
				api_request.dispose()
				playwright.stop()
		write_to_disk(save_in, HTML_PAGE_RESULT)
```

- [ ] **Step 2: Run the full proxies_providers test file**

Run: `python -m pytest tests/test_proxies_providers.py -v`
Expected: PASS (13 tests: 5 existing `_with_country_targeting` + 3 `_resolve_scrapingbee_key` + 5 `_fetch_via_scrapingbee`).

- [ ] **Step 3: Run ruff**

Run: `python -m ruff check sourcing_intel_cli/proxies_providers.py tests/test_proxies_providers.py`
Expected: `All checks passed!`

- [ ] **Step 4: Commit**

```bash
git add sourcing_intel_cli/proxies_providers.py
git commit -m "feat: accept a visitor-supplied ScrapingBee api_key override in sync_scraper"
```

---

## Task 3: `chart_builder.py` — ECharts migration

**Files:**
- Modify: `sourcing_intel_cli/chart_builder.py`
- Test: `tests/test_chart_builder.py`

**Interfaces:**
- Produces:
  - `SERIES_COLORS: list[str]` — module constant, `["#5b8ff9", "#e8524c", "#f6a5c0"]`.
  - `build_histogram_option(df: pd.DataFrame, numeric_col: str, title: str) -> dict`
  - `build_bar_option(df: pd.DataFrame, category_col: str, value_col: str, title: str, horizontal: bool = False) -> dict`
  - `build_box_option(df: pd.DataFrame, category_col: str, value_col: str, title: str) -> dict`
  - `build_scatter_option(df: pd.DataFrame, x_col: str, y_col: str, title: str) -> dict`
  - `build_chart(df: pd.DataFrame, chart_type: str, title: str = "", metric_col: str | None = None) -> dict | None` — same signature as before, now returns an ECharts `option` dict instead of a Plotly `go.Figure`.
  - `suggest_chart_type(question: str) -> str` — unchanged.
  - `CHART_TYPES` — unchanged.
- Consumes: nothing from other tasks (pure pandas/numpy).

This task replaces the whole file. Work through the four step groups below in order; each ends in its own commit.

### Step group A: shared scaffolding + histogram

- [ ] **Step 1: Write the failing tests**

Replace `tests/test_chart_builder.py` entirely with:
```python
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


def test_chart_types_lists_all_supported_types():
	assert set(CHART_TYPES) == {"none", "auto", "histogram", "bar", "box", "scatter"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_chart_builder.py -v`
Expected: FAIL — `build_chart` still returns Plotly figures / old code doesn't match.

- [ ] **Step 3: Replace `sourcing_intel_cli/chart_builder.py` with the new scaffold + histogram**

```python
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

	return None
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_chart_builder.py -v`
Expected: PASS for every test currently in the file (the ones added so far).

- [ ] **Step 5: Commit**

```bash
git add sourcing_intel_cli/chart_builder.py tests/test_chart_builder.py
git commit -m "feat: migrate chart_builder histogram to ECharts option dicts"
```

### Step group B: bar (including horizontal)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_chart_builder.py`, inside `TestBuildChart`:
```python
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
```

Add a new top-level test class at the end of the file, after `TestBuildChart`:
```python
class TestBuildBarOptionHorizontal:
	def test_horizontal_swaps_axes(self):
		from sourcing_intel_cli.chart_builder import build_bar_option

		df = pd.DataFrame({"supplier_name": ["Acme", "Beta"], "supplier_service_score": [4.8, 4.5]})
		option = build_bar_option(df, "supplier_name", "supplier_service_score", "Top", horizontal=True)
		assert option["yAxis"]["data"] == ["Acme", "Beta"]
		assert option["xAxis"]["name"] == "supplier_service_score"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_chart_builder.py -v`
Expected: FAIL — `build_bar_option` doesn't exist yet, bar branch of `build_chart` returns `None`.

- [ ] **Step 3: Implement**

In `sourcing_intel_cli/chart_builder.py`, add `build_bar_option` right after `build_histogram_option`:
```python
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
```

In `build_chart`, add the bar branch right after the histogram branch:
```python
	if chart_type == "bar":
		if not categorical_cols or not numeric_cols:
			return None
		return build_bar_option(df, categorical_cols[0], numeric_cols[0], title)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_chart_builder.py -v`
Expected: PASS for all tests so far.

- [ ] **Step 5: Commit**

```bash
git add sourcing_intel_cli/chart_builder.py tests/test_chart_builder.py
git commit -m "feat: migrate chart_builder bar chart to ECharts, add horizontal option"
```

### Step group C: box

- [ ] **Step 1: Write the failing test**

Add to `TestBuildChart` in `tests/test_chart_builder.py`:
```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_chart_builder.py::TestBuildChart::test_box_uses_categorical_and_numeric_columns -v`
Expected: FAIL — box branch still returns `None`.

- [ ] **Step 3: Implement**

In `sourcing_intel_cli/chart_builder.py`, add `build_box_option` right after `build_bar_option`:
```python
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
	for name, group in df.groupby(category_col)[value_col]:
		categories.append(str(name))
		box_data.append(group.quantile([0, 0.25, 0.5, 0.75, 1]).tolist())
	return {
		"title": {"text": title},
		"color": SERIES_COLORS,
		"tooltip": {},
		"xAxis": {"type": "category", "data": categories, "name": category_col},
		"yAxis": {"type": "value", "name": value_col},
		"series": [{"type": "boxplot", "data": box_data}],
	}
```

In `build_chart`, add the box branch right after the bar branch:
```python
	if chart_type == "box":
		if not categorical_cols or not numeric_cols:
			return None
		return build_box_option(df, categorical_cols[0], numeric_cols[0], title)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_chart_builder.py -v`
Expected: PASS for all tests so far.

- [ ] **Step 5: Commit**

```bash
git add sourcing_intel_cli/chart_builder.py tests/test_chart_builder.py
git commit -m "feat: migrate chart_builder boxplot to ECharts"
```

### Step group D: scatter

- [ ] **Step 1: Write the failing tests**

Add to `TestBuildChart` in `tests/test_chart_builder.py`:
```python
	def test_scatter_uses_two_numeric_columns(self):
		option = build_chart(self._df(), "scatter")
		assert option["series"][0]["type"] == "scatter"
		assert option["series"][0]["data"] == [[4.8, 1.2], [4.5, 3.4], [4.2, 2.1]]

	def test_scatter_with_only_one_numeric_column_returns_none(self):
		df = pd.DataFrame({"supplier_name": ["Acme", "Beta"], "min_price": [1.2, 3.4]})
		assert build_chart(df, "scatter") is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_chart_builder.py::TestBuildChart::test_scatter_uses_two_numeric_columns -v`
Expected: FAIL — scatter branch still returns `None`.

- [ ] **Step 3: Implement**

In `sourcing_intel_cli/chart_builder.py`, add `build_scatter_option` right after `build_box_option`:
```python
def build_scatter_option(df: pd.DataFrame, x_col: str, y_col: str, title: str) -> dict:
	"""Build an ECharts scatter-chart option.

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
	return {
		"title": {"text": title},
		"color": SERIES_COLORS,
		"tooltip": {},
		"xAxis": {"type": "value", "name": x_col},
		"yAxis": {"type": "value", "name": y_col},
		"series": [{"type": "scatter", "data": df[[x_col, y_col]].values.tolist()}],
	}
```

In `build_chart`, add the scatter branch right after the box branch, replacing the final `return None` fallback:
```python
	if chart_type == "scatter":
		if len(numeric_cols) < 2:
			return None
		return build_scatter_option(df, numeric_cols[0], numeric_cols[1], title)

	return None
```

- [ ] **Step 4: Run the full file**

Run: `python -m pytest tests/test_chart_builder.py -v`
Expected: PASS — all 20 tests (8 `TestSuggestChartType` + 10 `TestBuildChart` + 1 `TestBuildBarOptionHorizontal` + 1 `test_chart_types_lists_all_supported_types`).

- [ ] **Step 5: Run ruff**

Run: `python -m ruff check sourcing_intel_cli/chart_builder.py tests/test_chart_builder.py`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add sourcing_intel_cli/chart_builder.py tests/test_chart_builder.py
git commit -m "feat: migrate chart_builder scatter chart to ECharts"
```

---

## Task 4: Dark theme

**Files:**
- Modify: `.streamlit/config.toml`

**Interfaces:**
- Consumes: nothing.
- Produces: Streamlit's dark theme applied app-wide (consumed visually by Task 5's pages — no code interface).

- [ ] **Step 1: Edit `.streamlit/config.toml`**

The file currently has only a `[client]` section (from the earlier `showErrorDetails` fix). Add a `[theme]` section — full file becomes:
```toml
# Uncaught exceptions must never dump a Python traceback/code on the page —
# only a generic message. Full details (type, message, traceback) still go
# to the terminal console, and to logs/app.log via sourcing_intel_cli's
# loguru file sink for exceptions we catch explicitly with logger.exception.
[client]
showErrorDetails = "none"

# Dark theme matching the reference design: near-black background, a
# crimson/red accent for the active nav item and buttons.
[theme]
base = "dark"
primaryColor = "#e63946"
backgroundColor = "#0b0d12"
secondaryBackgroundColor = "#151822"
textColor = "#e6e6e6"
font = "sans serif"
```

- [ ] **Step 2: Verify the config is picked up**

Run: `python -m streamlit config show 2>&1 | grep -A1 "theme"` (or on Windows PowerShell: `python -m streamlit config show | Select-String -Pattern "theme" -Context 0,2`)
Expected: `primaryColor = "#e63946"` and the other new values appear, each prefixed with `>` (meaning "explicitly set", not default) — same pattern already used to verify `showErrorDetails` earlier in this project.

- [ ] **Step 3: Commit**

```bash
git add .streamlit/config.toml
git commit -m "feat: add dark theme matching the reference design"
```

---

## Task 5: `app.py` — navigation restructure, ECharts wiring, Aide page, BYO key + banner

**Files:**
- Modify: `app.py` (full rewrite)

**Interfaces:**
- Consumes:
  - `sourcing_intel_cli.chart_builder.{build_chart, build_histogram_option, build_bar_option, build_box_option, suggest_chart_type}` (Task 3)
  - `sourcing_intel_cli.proxies_providers.ScrapingBeeQuotaExceeded` (Task 2)
  - `streamlit_echarts.st_echarts` (Task 1)
  - Everything else already imported in the current `app.py` (`data_quality`, `datasets`, `demo_data`, `engine_and_database`, `proxies_providers.{BrightDataProxyProvider, ScrapingBeeProxyProvider}`, `scrape_from_disk.PageParser`, `typed_datas`).
- Produces: nothing consumed by later tasks — this is the last code task.

This is a UI script with no automated tests (consistent with the rest of the project — Streamlit pages aren't unit-testable). Verification is: the app boots without exceptions, and a human confirms each page visually. Do the whole rewrite in one pass, then verify, then one commit.

- [ ] **Step 1: Replace `app.py` in full**

```python
"""Sourcing Intel — multi-page Streamlit app: scrape, validate, browse, and
ask natural-language questions about product/supplier data.

Four pages via st.navigation: Accueil (landing), Explorer (dataset picker +
NL search + charts), Scraper (live scraping + demo data), Aide (onboarding
guide). Replaces the old CLI (commands.py) and MCP server (mcp_server.py).
Run with: streamlit run app.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st
from loguru import logger
from sqlmodel import SQLModel
from streamlit_echarts import st_echarts

from sourcing_intel_cli.chart_builder import (
	build_bar_option,
	build_box_option,
	build_chart,
	build_histogram_option,
	suggest_chart_type,
)
from sourcing_intel_cli.data_quality import (
	run_quality_checks,
	write_quality_report,
)
from sourcing_intel_cli.datasets import DB_PREFIX, dataset_label, discover_databases, slugify
from sourcing_intel_cli.demo_data import generate_demo_data
from sourcing_intel_cli.engine_and_database import (
	add_products_to_db,
	add_suppliers_to_db,
	create_db_engine,
	save_all_changes,
)
from sourcing_intel_cli.nl_search import apply_query_spec, build_query_spec
from sourcing_intel_cli.proxies_providers import (
	BrightDataProxyProvider,
	ScrapingBeeProxyProvider,
	ScrapingBeeQuotaExceeded,
)
from sourcing_intel_cli.product_naming import summarize_product_names
from sourcing_intel_cli.scrape_from_disk import PageParser
from sourcing_intel_cli.typed_datas import ProductDict, SupplierDict


# ---------------------------------------------------------------------------
# Data access (read-only for the search/charts section)
# ---------------------------------------------------------------------------


def load_products_with_suppliers(db_path: Path) -> pd.DataFrame:
	"""Read products joined with suppliers from the given SQLite DB.

	Read-only: a plain SELECT via pandas, never a write path. This is what
	backs both the charts and the natural-language search — the same
	structural guarantee the old CSV-only ai-agent had (no direct DB access
	from a natural-language query), just without the extra CSV export step.

	:param db_path: Path to the database file to read from — one per search,
		see `discover_databases`.
	:type db_path: Path
	:return: DataFrame with one row per product, joined to its supplier. Empty
		DataFrame if the database doesn't exist.
	:rtype: pd.DataFrame
	"""
	if not db_path.exists():
		return pd.DataFrame()

	import sqlite3

	query = """
      SELECT Product.name as product_name,
      Product.short_name as short_name,
      Product.min_price as min_price,
      Product.max_price as max_price,
      Product.product_score as product_score,
      Product.review_count as review_count,
      Product.review_score as review_score,
      Product.trade_product as trade_product,
      Supplier.name as supplier_name,
      Supplier.country_name as country_name,
      Supplier.sopi_level as sopi_level,
      Supplier.years_as_gold_supplier as years_as_gold_supplier,
      Supplier.supplier_service_score as supplier_service_score
      FROM Product
      JOIN Supplier ON Product.supplier_id = Supplier.id"""
	with sqlite3.connect(db_path) as con:
		return pd.read_sql_query(query, con)


def _validate_and_insert(
	raw_suppliers: list[SupplierDict], raw_products: list[ProductDict], db_name: str
) -> None:
	"""Run the quality agent then write clean rows to the DB, with Streamlit feedback.

	Shared by the live scraper and the demo dataset loader so both sources go
	through the exact same validation/insertion path.

	:param raw_suppliers: Suppliers straight from the source (scraper or demo data).
	:type raw_suppliers: list[SupplierDict]
	:param raw_products: Products straight from the source (scraper or demo data).
	:type raw_products: list[ProductDict]
	:param db_name: Database name (without `.sqlite`) to write to — one per
		search, so different searches' results never mix.
	:type db_name: str
	"""
	with st.spinner("Validation qualité..."):
		suppliers, products, issues = run_quality_checks(raw_suppliers, raw_products)
		write_quality_report(issues)

	if issues:
		st.warning(f"{len(issues)} ligne(s) rejetée(s) par l'agent de qualité — voir détail ci-dessous.")
		with st.expander("Détail des rejets"):
			st.dataframe(
				pd.DataFrame(
					[
						{"entité": i.entity, "id": i.identifier, "champ": i.field, "raison": i.reason}
						for i in issues
					]
				)
			)
	else:
		st.success("Aucun problème de qualité détecté.")

	if not suppliers and not products:
		st.error("Tout a été rejeté, rien à insérer.")
		st.stop()

	if products:
		with st.spinner("Résumé des noms de produits trop longs..."):
			short_names = summarize_product_names([p["name"] for p in products])
			for product in products:
				product["short_name"] = short_names[product["name"]]

	with st.spinner("Écriture en base..."):
		try:
			engine = create_db_engine(db_name=db_name)
			save_all_changes(engine_db=engine, sql_model=SQLModel)
			add_suppliers_to_db(suppliers=suppliers, engine_db=engine)
			add_products_to_db(products=products, engine_db=engine)
		except Exception as e:  # noqa: BLE001
			logger.exception("Database write failed")
			st.error(f"L'écriture en base a échoué : {e}\n\nVoir logs/app.log pour le détail.")
			st.stop()

	st.success(f"{len(suppliers)} fournisseur(s) et {len(products)} produit(s) ajoutés.")
	st.cache_data.clear()


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


def page_accueil() -> None:
	"""Landing page: pitch, quota banner, links to the other pages."""
	st.title("🔍 Sourcing Intel")
	st.markdown(
		"""
		**Sourcing Intel** scrape une marketplace B2B, valide et stocke les
		données, puis te laisse les explorer par recherche en langage
		naturel et par graphiques — comme un·e acheteur·se qui compare des
		centaines de fournisseurs sans ouvrir un seul onglet en plus.

		Projet de portfolio, à but éducatif — pas un produit commercial.
		"""
	)
	if st.session_state.get("sb_quota_exhausted"):
		st.warning(
			"⚠️ La clé ScrapingBee de démo est épuisée pour l'instant — "
			"récupère la tienne gratuitement, voir la page **Aide**."
		)
	st.markdown("**Pour commencer :**")
	col_explorer, col_scraper, col_aide = st.columns(3)
	with col_explorer:
		st.page_link(PAGE_EXPLORER, label="Explorer les données")
	with col_scraper:
		st.page_link(PAGE_SCRAPER, label="Lancer un scraping")
	with col_aide:
		st.page_link(PAGE_AIDE, label="Guide d'utilisation")


def page_explorer() -> None:
	"""Dataset picker + natural-language search + charts."""
	st.title("Explorer")
	databases = discover_databases()

	if not databases:
		st.info("Aucune donnée pour l'instant — va sur la page **Scraper** pour lancer un scraping.")
		return

	dataset_labels = {dataset_label(p): p for p in databases}
	selected_label = st.selectbox(
		"Jeu de données à explorer",
		list(dataset_labels.keys()),
		help="Chaque recherche a sa propre base — choisis laquelle explorer.",
	)
	df = load_products_with_suppliers(dataset_labels[selected_label])

	if df.empty:
		st.info("Ce jeu de données est vide.")
		return

	tab_search, tab_charts = st.tabs(["💬 Recherche en langage naturel", "📊 Graphiques"])

	with tab_search:
		st.info(
			"🧑‍💼 **Mets-toi dans la peau d'un entrepreneur qui veut sourcer un produit "
			"sur Alibaba.** Tu as des centaines de fournisseurs sous les yeux, tous avec "
			"des prix, des notes et des garanties différentes — tu veux trouver les "
			"meilleurs fournisseurs, au meilleur prix, sans passer des heures à comparer "
			"des lignes à la main. C'est exactement ce que cette recherche permet de faire : "
			"pose ta question en langage naturel, elle filtre/trie les données pour toi."
		)

		with st.expander("📋 Champs disponibles dans les données"):
			col_product, col_supplier = st.columns(2)
			with col_product:
				st.markdown(
					"""
					**Produit**
					- `product_name` — nom complet du produit (parfois long)
					- `short_name` — version raccourcie, plus lisible en tableau/graphique
					- `min_price` / `max_price` — fourchette de prix (USD)
					- `product_score` — note du produit (sur 5)
					- `review_count` / `review_score` — nombre d'avis et note moyenne
					- `trade_product` — protégé par Trade Assurance (vrai/faux)
					"""
				)
			with col_supplier:
				st.markdown(
					"""
					**Fournisseur**
					- `supplier_name` — nom du fournisseur
					- `country_name` — pays du fournisseur
					- `sopi_level` — niveau de performance (1 à 5)
					- `years_as_gold_supplier` — ancienneté Gold Supplier
					- `supplier_service_score` — note de service (sur 5)
					"""
				)
			st.caption(
				"Chaque ligne = un produit relié à son fournisseur — tu peux combiner "
				"des critères des deux côtés dans une même question."
			)

		st.markdown("**Exemples de questions à poser :**")
		st.markdown(
			"""
			- *Quels sont les 5 fournisseurs avec le meilleur supplier_service_score ?*
			- *Trouve les produits les moins chers avec un product_score au-dessus de 4.5.*
			- *Liste les fournisseurs en Chine avec au moins 5 ans d'ancienneté Gold Supplier, triés par prix minimum.*
			- *Quel produit a le meilleur rapport qualité-prix (bonne note, prix bas) ?*
			- *Compare le prix moyen des produits par pays fournisseur.*
			- *Montre les fournisseurs les mieux notés qui offrent la Trade Assurance.*
			"""
		)

		query = st.text_input(
			"Pose ta question sur les produits/fournisseurs",
			placeholder="ex: quels sont les 5 fournisseurs les mieux notés en Chine ?",
		)
		chart_type_labels = {
			"Auto (selon la question)": "auto",
			"Tableau seulement": "none",
			"Histogramme": "histogram",
			"Barres": "bar",
			"Boîte à moustaches": "box",
			"Nuage de points": "scatter",
		}
		chart_type_choice = st.selectbox("Type de graphique", list(chart_type_labels.keys()))

		if st.button("Chercher", disabled=not query):
			with st.spinner("Recherche en cours..."):
				try:
					# The LLM only ever returns a small filter/sort/select spec — we
					# execute it ourselves with pandas. No LLM-generated code runs.
					spec = build_query_spec(query, df)
					result = apply_query_spec(df, spec)
				except RuntimeError as e:
					st.error(str(e))
					st.stop()
				except Exception:  # noqa: BLE001
					logger.exception("Natural-language search failed")
					st.error(
						"La recherche a échoué. Réessaie avec une autre formulation, "
						"ou réessaie plus tard si le problème persiste."
					)
					st.stop()
			if result.empty:
				st.warning("Aucun résultat pour cette question.")
			else:
				chart_type = chart_type_labels[chart_type_choice]
				resolved_type = suggest_chart_type(query) if chart_type == "auto" else chart_type
				option = (
					build_chart(result, resolved_type, title=query, metric_col=spec.get("sort_by"))
					if resolved_type != "none"
					else None
				)
				if option is not None:
					st_echarts(options=option, theme="dark")
					with st.expander("Voir les données du graphique"):
						st.dataframe(result, use_container_width=True)
				else:
					if resolved_type != "none":
						st.caption(
							f"Pas assez de colonnes adaptées pour un graphique « {resolved_type} » "
							"avec ce résultat — affichage en tableau."
						)
					st.dataframe(result, use_container_width=True)
		st.caption(
			"Cette recherche lit uniquement une copie en mémoire des données (lecture seule) — "
			"jamais d'écriture en base depuis une requête en langage naturel."
		)

	with tab_charts:
		col1, col2 = st.columns(2)
		with col1:
			option_price = build_histogram_option(df, "min_price", "Distribution des prix minimums")
			st_echarts(options=option_price, theme="dark")
		with col2:
			top_suppliers = (
				df.groupby("supplier_name")["supplier_service_score"]
				.mean()
				.sort_values(ascending=False)
				.head(10)
				.reset_index()
			)
			option_suppliers = build_bar_option(
				top_suppliers,
				"supplier_name",
				"supplier_service_score",
				"Top 10 fournisseurs par score de service",
				horizontal=True,
			)
			st_echarts(options=option_suppliers, theme="dark")

		option_country = build_box_option(
			df, "country_name", "min_price", "Distribution des prix par pays fournisseur"
		)
		st_echarts(options=option_country, theme="dark")


def page_scraper() -> None:
	"""Live scraping controls, demo dataset loader, and the ScrapingBee BYO-key field."""
	st.title("Scraper")

	if st.session_state.get("sb_quota_exhausted"):
		st.warning(
			"⚠️ La clé ScrapingBee de démo est épuisée pour l'instant — "
			"récupère la tienne gratuitement (voir la page **Aide**) ou saisis-la ci-dessous."
		)

	keywords = st.text_input("Mots-clés", placeholder="ex: wireless earbuds")
	provider_name = st.selectbox("Fournisseur de proxy", ["scrapingbee", "brightdata"])
	page_results = st.number_input("Nombre de pages", min_value=1, max_value=50, value=5)

	user_scrapingbee_key = None
	if provider_name == "scrapingbee":
		user_scrapingbee_key = st.text_input(
			"Ta clé ScrapingBee (facultatif)",
			type="password",
			help="Laisse vide pour utiliser la clé de démo du site. Voir la page "
			"Aide pour savoir où trouver la tienne, gratuitement.",
		)
		st.session_state["user_scrapingbee_key"] = user_scrapingbee_key

	if st.button("Scraper en direct", type="primary", disabled=not keywords):
		provider_cls = {
			"brightdata": BrightDataProxyProvider,
			"scrapingbee": ScrapingBeeProxyProvider,
		}[provider_name]
		slug = slugify(keywords)
		save_in_folder = f"scraped_pages/{slug}"

		with st.spinner("Scraping en cours (peut prendre plusieurs minutes)..."):
			try:
				if provider_name == "scrapingbee":
					provider_cls.sync_scraper(
						save_in=save_in_folder,
						key_words=keywords,
						page_results=int(page_results),
						api_key=user_scrapingbee_key or None,
					)
				else:
					provider_cls.sync_scraper(
						save_in=save_in_folder, key_words=keywords, page_results=int(page_results)
					)
			except ScrapingBeeQuotaExceeded:
				logger.exception("ScrapingBee quota exceeded")
				st.session_state["sb_quota_exhausted"] = True
				st.error(
					"La clé ScrapingBee a épuisé son quota de crédits. Récupère la "
					"tienne gratuitement (voir la page Aide) ou saisis-la ci-dessus."
				)
				st.stop()
			except Exception as e:  # noqa: BLE001
				logger.exception("Scraping failed")
				st.error(f"Le scraping a échoué : {e}\n\nVoir logs/app.log pour le détail.")
				st.stop()

		with st.spinner("Analyse des pages..."):
			try:
				page_parser = PageParser(targeted_folder=save_in_folder)
				raw_suppliers = page_parser.detected_suppliers()
				raw_products = page_parser.detected_products()
			except Exception:  # noqa: BLE001
				logger.exception("Page parsing failed")
				st.error("L'analyse des pages scrapées a échoué. Voir logs/app.log pour le détail.")
				st.stop()

		_validate_and_insert(raw_suppliers, raw_products, db_name=f"{DB_PREFIX}_{slug}")

	st.divider()
	st.caption(
		"Le site cible change parfois de structure et peut casser le scraping en "
		"direct — utilise le jeu de démo pour explorer l'app sans dépendre du site."
	)
	if st.button("Charger le jeu de données de démo"):
		raw_suppliers, raw_products = generate_demo_data()
		_validate_and_insert(raw_suppliers, raw_products, db_name=f"{DB_PREFIX}_demo")


def page_aide() -> None:
	"""Onboarding guide: free ScrapingBee key, data architecture, how to use the app."""
	st.title("❓ Aide")

	st.header("1. Obtenir une clé ScrapingBee gratuite")
	st.markdown(
		"""
		1. Va sur [scrapingbee.com](https://www.scrapingbee.com) et crée un
		   compte gratuit (email + mot de passe, ou via Google/GitHub).
		2. Une fois connecté·e, ton tableau de bord affiche ta clé API en
		   haut de la page, sous **API Key** — copie-la avec l'icône à côté.
		3. Le plan gratuit inclut un nombre de crédits d'essai (vérifie le
		   montant exact sur leur page de tarifs, ça peut changer) —
		   largement de quoi tester cette app.
		4. Reviens sur la page **Scraper** de ce site, colle ta clé dans le
		   champ *"Ta clé ScrapingBee (facultatif)"*.
		"""
	)

	st.header("2. Comment les données sont organisées")
	st.markdown(
		"""
		Chaque recherche que tu lances (un jeu de mots-clés) crée sa **propre
		base de données** — un fichier séparé, nommé d'après ta recherche.
		Les résultats de deux recherches différentes ne se mélangent jamais.

		Sur la page **Explorer**, le sélecteur *"Jeu de données à
		explorer"* te permet de choisir laquelle de tes recherches passées
		regarder — y compris le jeu de données de démo.
		"""
	)

	st.header("3. Mode d'emploi")
	st.markdown(
		"""
		**Scraper en direct vs jeu de démo** — le scraping en direct dépend
		de la structure du site cible, qui change parfois ; si ça casse,
		utilise le bouton *"Charger le jeu de données de démo"* sur la page
		**Scraper** pour explorer l'app sans dépendre du site.

		**Poser une question en langage naturel** — sur la page **Explorer**,
		décris ce que tu cherches en une phrase (ex. *"les 5 fournisseurs les
		mieux notés en Chine"*). La question est transformée en filtre/tri
		déterministe, jamais en code généré par une IA exécuté à l'aveugle.

		**Lire les graphiques** — un histogramme montre une distribution
		(ex. répartition des prix), un graphique en barres compare des
		catégories (ex. top fournisseurs), une boîte à moustaches montre la
		dispersion des prix par groupe (ex. par pays), un nuage de points
		montre une relation entre deux valeurs numériques.
		"""
	)


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Sourcing Intel", layout="wide")

PAGE_ACCUEIL = st.Page(page_accueil, title="Accueil", icon="🏠", default=True)
PAGE_EXPLORER = st.Page(page_explorer, title="Explorer", icon="🔍")
PAGE_SCRAPER = st.Page(page_scraper, title="Scraper", icon="🕷️")
PAGE_AIDE = st.Page(page_aide, title="Aide", icon="❓")

pg = st.navigation([PAGE_ACCUEIL, PAGE_EXPLORER, PAGE_SCRAPER, PAGE_AIDE])
pg.run()
```

- [ ] **Step 2: Run ruff**

Run: `python -m ruff check app.py`
Expected: `All checks passed!` — fix any import-order or unused-import warnings ruff reports before moving on.

- [ ] **Step 3: Run the full test suite (nothing in app.py is tested, but this catches any import-time breakage in modules it pulls in)**

Run: `python -m pytest -q`
Expected: all tests still pass (this file has no direct tests, but `product_naming`, `nl_search`, etc. must still import cleanly).

- [ ] **Step 4: Start the server and verify it boots**

```bash
python -m streamlit run app.py --server.port 8501
```
Then, in a separate check: `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8501` → expect `200`, and check the terminal/`logs/app.log` for import or startup errors.

- [ ] **Step 5: Manual walkthrough (human-verified — list each check explicitly rather than a vague "click around")**

Ask the human to confirm, one by one:
- Sidebar shows 4 nav items: Accueil, Explorer, Scraper, Aide, with the dark theme applied.
- **Accueil**: pitch text renders, the 3 links navigate to Explorer/Scraper/Aide respectively.
- **Explorer**: dataset picker lists existing databases (including the legacy `sourcing_intel.sqlite` if present); NL search returns a chart rendered via ECharts (not a blank area); the 3 fixed charts in "Graphiques" render (histogram, horizontal bar, boxplot).
- **Scraper**: keyword/provider/page-count fields present; ScrapingBee key field only appears when "scrapingbee" is selected; demo-data button still works end-to-end (inserts into a `sourcing_intel_demo.sqlite`, visible afterward on Explorer).
- **Aide**: all 3 sections render with readable content.
- If credits allow: trigger a real ScrapingBee 429 (or temporarily hardcode a bad/exhausted key) to confirm the quota banner appears on both Scraper and Accueil, and that entering a key in the BYO field is used on the next attempt.

- [ ] **Step 6: Commit**

```bash
git add app.py
git commit -m "feat: restructure app.py into navigation pages, ECharts, BYO ScrapingBee key"
```

---

## Task 6: Full regression, cleanup, final verification

**Files:**
- Modify: `requirements.txt` (remove `plotly`)

**Interfaces:**
- Consumes: everything from Tasks 1–5.
- Produces: nothing further — this closes out the plan.

- [ ] **Step 1: Confirm nothing imports plotly anymore**

Search `app.py` and every file under `sourcing_intel_cli/` for the string `plotly` (use the Grep tool, or `Select-String -Pattern plotly -Path app.py, sourcing_intel_cli\*.py` in PowerShell).
Expected: zero matches outside of `requirements.txt` itself.

- [ ] **Step 2: Remove `plotly` from `requirements.txt`**

Delete the `plotly>=5.20` line.

- [ ] **Step 3: Reinstall to confirm the app still works without it**

Run: `python -m pip uninstall -y plotly`
Run: `python -m pytest -q`
Expected: all tests still pass with `plotly` uninstalled (proves nothing depends on it anymore).

- [ ] **Step 4: Full lint pass**

Run: `python -m ruff check .`
Expected: `All checks passed!`

- [ ] **Step 5: Restart the server one final time and re-verify manually**

Run `python -m streamlit run app.py --server.port 8501`, confirm `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8501` returns `200` with no errors in `logs/app.log`, then ask the human to re-confirm the same checks as before: all 4 nav pages load; Explorer's NL search and all 3 fixed charts (histogram, horizontal bar, boxplot) render via ECharts; Scraper's demo-data button still inserts and shows up on Explorer. This confirms removing `plotly` didn't break anything visually.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt
git commit -m "chore: remove plotly, fully replaced by ECharts"
```

---

## Follow-ups (not part of this plan)

- Update `CLAUDE.md`'s architecture/structure sections to describe the new
  multi-page navigation, ECharts, and BYO-key flow (deferred per the spec —
  do this once the app is confirmed working end-to-end).
- Tune exact theme hex values and chart series colors against the reference
  screenshot once the dark theme is visible in a real browser — the values
  in Task 4/Task 3 are a reasonable starting point, not pixel-final.
