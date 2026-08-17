# Dark redesign, ECharts migration, Aide page, BYO ScrapingBee key

Status: approved in chat (sections A–G), pending written spec review.

## 1. Context

The app currently has one Streamlit page: a sidebar with scraper controls,
and a main area with a dataset picker + two tabs (Recherche NL / Graphiques),
all rendered with default Streamlit theming and Plotly charts.

The user shared a reference screenshot (a "Snowflake Healthcare App" Streamlit
demo): near-black background, a real sidebar navigation menu (icon + label
list, one item highlighted in red/crimson), a bold page title, and charts
that float directly on the dark background with no card/border, arranged in
a grid, using blue/red/pink series colors on dark chart backgrounds.

Three things are being built together because they touch the same surfaces
(`app.py`, the sidebar, the chart rendering path):

1. Restructure navigation into real pages (matching the reference's IA) and
   apply its dark/red visual language throughout.
2. Replace Plotly with ECharts (via `streamlit-echarts`) for every chart.
3. Add an "Aide" page (onboarding guide) plus a bring-your-own-API-key flow
   for ScrapingBee, since the owner's key will eventually run out of credits.

## 2. Goals

- Visitors landing on the app understand what it does and how to get their
  own free ScrapingBee key without leaving the app.
- The whole app (nav, charts, typography) reads as one deliberately designed
  dark UI, not default Streamlit chrome with a title slapped on.
- All charts render via ECharts, not Plotly.
- When the shared ScrapingBee key runs out of credits, visitors get a clear,
  specific explanation and a way to use their own key immediately — not a
  generic "scraping failed" error.

## 3. Non-goals

- No change to the scraping/parsing/data-quality pipeline itself (covered by
  recent work: per-search DBs, currency geo-pinning, resilient parsing).
- No BrightData BYO-key flow — BrightData requires a paid Scraping Browser
  subscription, so there's no "get one free" story for it. Only ScrapingBee
  gets the visitor-key treatment.
- No real browser cookie / cross-session persistence for the quota-exhausted
  signal — `st.session_state` only (per open tab). Decided in chat: avoids
  pulling in a cookie library and the consent-banner obligation that comes
  with a non-essential cookie, for a portfolio app where "resets on next
  visit" is an acceptable trade-off.
- No packaging/versioning work (Commitizen, pipx) — already deferred
  separately, unrelated to this change.

## 4. Navigation & page structure

Replace the sidebar-as-scraper-controls layout with `st.navigation` +
`st.Page`, four pages, all as functions inside `app.py` (no `pages/`
directory — keeps `app.py` the single entry point, per CLAUDE.md):

| Page | Icon | Content |
|---|---|---|
| Accueil | 🏠 | Pitch/intro, link to Aide, ScrapingBee quota banner if applicable, call-to-action links to Explorer/Scraper |
| Explorer | 🔍 | Dataset picker + today's two tabs (Recherche NL / Graphiques), now ECharts-rendered |
| Scraper | 🕷️ | Today's sidebar controls (keywords, provider, page count, live-scrape button, demo-data button) + the new "your own ScrapingBee key" field + quota banner |
| Aide | ❓ | Onboarding guide (section 6) |

**Deviation from the chat outline:** section A originally put the dataset
picker on Accueil. Moving it: `st.navigation` pages are independent script
runs, so a selection made in a widget on Accueil isn't visible on Explorer
without extra session-state plumbing for no benefit — the picker is only
ever consumed on Explorer, so it lives there. Accueil stays a pure
welcome/orientation page. Flagging this now for the spec review; easy to
revert if you'd rather see the picker on Accueil too.

```python
pg = st.navigation([
    st.Page(page_accueil, title="Accueil", icon="🏠", default=True),
    st.Page(page_explorer, title="Explorer", icon="🔍"),
    st.Page(page_scraper, title="Scraper", icon="🕷️"),
    st.Page(page_aide, title="Aide", icon="❓"),
])
pg.run()
```

`st.navigation`/`st.Page` need Streamlit ≥1.36 (installed: 1.61.1, already
fine) — `requirements.txt`'s floor (`streamlit>=1.35`) gets bumped to
`>=1.36` so a fresh install can't land on a version too old for this.

## 5. Visual design system

`.streamlit/config.toml` (already exists for `showErrorDetails`) gains a
`[theme]` section:

- `base = "dark"`, near-black background (`#0e1117`-ish, matching the
  reference), red/crimson primary accent (`#e63946`-ish) for the active nav
  item and buttons.
- Bold sans-serif for the page title (Streamlit's default theme font is
  close enough — no custom font loading, keeps things simple).
- Charts get no `st.container(border=True)` / card wrapper — they sit
  directly on the page background, matching the reference's borderless
  grid-of-charts look. The Graphiques sub-tab keeps its existing
  `st.columns(2)` grid.

Exact hex values get tuned during implementation against the reference
image; this section fixes the direction (near-black + red accent, borderless
charts), not final pixel values.

## 6. ECharts migration

**Dependency:** add `streamlit-echarts` to `requirements.txt`.

**Interface change:** `chart_builder.build_chart` currently returns
`go.Figure | None`. It changes to return `dict | None` — an ECharts
`option` object, passed straight to `st_echarts(options=option,
theme="dark")`. This is a breaking change to `build_chart`'s contract, so
every call site and every existing test in `tests/test_chart_builder.py`
needs updating (currently asserts `isinstance(fig, go.Figure)` and reads
`fig.data[0].y[0]` — becomes asserting dict shape and reading
`option["series"][0]["data"][...]`).

`suggest_chart_type` is untouched — chart *type* selection is independent
of the rendering library.

**Per-chart-type mapping** (same four types, same column-selection logic —
`metric_col` preference, first categorical/numeric column — just a
different `option` dict shape as output):

- `histogram`: ECharts has no built-in binning. Bin the numeric column with
  `numpy.histogram` (30 bins, matching today's `nbins=30`) and render as a
  `bar` series with bin-range labels on the category axis.
- `bar`: straightforward `bar` series — `xAxis.data` = categories,
  `series[0].data` = values.
- `box`: ECharts' `boxplot` series needs `[min, Q1, median, Q3, max]`
  already computed per category — no client-side stats helper available
  from Python, so compute quartiles per group with
  `df.groupby(cat_col)[num_col].quantile([...])` before building the option.
- `scatter`: `scatter` series, `data` = list of `[x, y]` pairs.

**Fixed dashboard charts** (today's `tab_charts` in `app.py`, built directly
with `px.histogram`/`px.bar`/`px.box`) move to using the same
histogram/bar/boxplot construction helpers from `chart_builder.py` instead
of duplicating chart-building logic in `app.py` — the "top 10 suppliers"
horizontal bar becomes a `bar` series with the category axis on `yAxis`
instead of `xAxis`.

**Color palette:** a small shared constant in `chart_builder.py` (e.g.
`SERIES_COLORS = ["#5b8ff9", "#e8524c", "#f6a5c0"]` — blue/red/pink,
matching the reference image's chart colors) applied via `option["color"]`.
Exact values tuned during implementation.

## 7. Aide page content

Three sections, in order:

1. **Obtenir une clé ScrapingBee gratuite** — numbered steps (sign up on
   scrapingbee.com, free tier credit amount, where to find the API key in
   their dashboard, paste it into the Scraper page's key field).
2. **Comment les données sont organisées** — plain-language explanation of
   the per-search-database architecture (`datasets.py`): each search gets
   its own SQLite file, the Explorer page's dataset picker is how you switch
   between past searches, nothing gets mixed together.
3. **Mode d'emploi** — live scraping vs. demo dataset (and why the demo
   button exists — live scraping depends on a site that changes structure),
   how to phrase a natural-language question, how to read the charts.

Static content (`st.markdown`), no dynamic data — lives entirely in the
`page_aide()` function.

## 8. BYO ScrapingBee key + quota-exhausted banner

**Session state keys:**
- `st.session_state["user_scrapingbee_key"]` — set by the optional
  password-masked `st.text_input` on the Scraper page. Never written to
  disk, never sent anywhere except as the `api_key` param on that visitor's
  own scrape calls.
- `st.session_state["sb_quota_exhausted"]` — bool, `False` until a 429 is
  observed, then stays `True` for the rest of the browser tab's session.

**Provider interface change:** `ScrapingBeeProxyProvider.sync_scraper` gains
an optional `api_key: str | None = None` param. Resolution order inside:
`api_key or cls.SB_API_KEY` — falls back to the owner's `.env` key when the
visitor hasn't supplied their own. The existing "no key at all" `RuntimeError`
still fires if both are empty.

**Quota detection:** ScrapingBee returns HTTP 429 with body
`{"error": {"message": "You exceeded your current quota..."}}` specifically
for credit exhaustion (confirmed against their docs) — distinct from 401
(invalid/missing key). A new `ScrapingBeeQuotaExceeded(RuntimeError)`
exception is raised the moment a 429 is seen (instead of the current
`logger.warning(...); continue`, which would otherwise burn through every
remaining page hitting the same 429). `app.py`'s Scraper page catches this
specific exception before the generic `Exception` handler, sets
`st.session_state["sb_quota_exhausted"] = True`, and shows the banner
instead of a generic scraping-failed error.

**Banner copy** (Scraper page, and a shorter link-style mention on
Accueil, both gated on `st.session_state.get("sb_quota_exhausted")`):
> "La clé démo est épuisée pour l'instant — récupère la tienne gratuitement
> (voir Aide) ou saisis-la ci-dessous."

## 9. File-level change map

- `app.py` — rewritten around `st.navigation`; sidebar controls move into
  `page_scraper()`; dataset picker + tabs move into `page_explorer()`; new
  `page_accueil()`, `page_aide()`.
- `sourcing_intel_cli/chart_builder.py` — `build_chart` returns ECharts
  option dicts; new histogram-binning and boxplot-quartile helpers.
- `sourcing_intel_cli/proxies_providers.py` — `ScrapingBeeProxyProvider`
  gains `api_key` param and `ScrapingBeeQuotaExceeded` exception.
- `.streamlit/config.toml` — add `[theme]` section.
- `requirements.txt` — add `streamlit-echarts`; bump `streamlit` floor to
  `>=1.36`.
- `tests/test_chart_builder.py` — rewritten assertions for dict-shaped
  output.
- `tests/test_proxies_providers.py` — new tests for the `api_key` override
  and 429 → `ScrapingBeeQuotaExceeded` behavior (mocked HTTP response, no
  real network).
- `CLAUDE.md` — structure/behavior sections updated after implementation to
  match (multipage nav, ECharts, BYO key) — tracked as a follow-up, not part
  of the implementation plan itself.

## 10. Testing strategy

- `chart_builder.py`: pure functions, same unit-test shape as today, just
  asserting on dict structure instead of `go.Figure` — every existing case
  (empty df, missing columns, metric_col preference, unknown type) carries
  over.
- `proxies_providers.py`: the `api_key` fallback logic and 429 detection are
  pure enough to unit test with a stubbed `api_request.get` (no real
  ScrapingBee call) — following the existing pattern of only unit-testing
  the non-network parts of this module (see `_with_country_targeting`'s
  tests).
- No automated test for the visual theme or page navigation itself
  (Streamlit UI, not unit-testable) — verified manually by running the app,
  consistent with how the per-search-database and dark-UI work has been
  checked so far in this project.

## 11. Open risks

- ECharts' `boxplot` series requires quartiles computed up front — if a
  category has only 1-2 data points, `quantile` on a tiny group can produce
  a degenerate box (min=Q1=median). Not a new problem (Plotly's `px.box` box
  had the same edge case), just noting it carries over unchanged.
- `st.navigation` changes the URL structure (each page gets its own query
  param) — no impact expected since this app isn't deployed with bookmarked
  deep links today, but worth a quick manual check after implementation.
