# PickMySupplier

<p align="center"><b>Scrape a B2B marketplace, validate the data, and query it in plain English.</b></p>

<div align="center">

[![CI](https://github.com/poneoneo/pickmysupplier/actions/workflows/ci.yml/badge.svg)](https://github.com/poneoneo/pickmysupplier/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/poneoneo/pickmysupplier/branch/main/graph/badge.svg)](https://codecov.io/gh/poneoneo/pickmysupplier)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![Streamlit](https://img.shields.io/badge/streamlit-1.36%2B-FF4B4B?logo=streamlit&logoColor=white)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-support-FF5E5B?logo=kofi&logoColor=white)](https://ko-fi.com/poneoneo)

</div>

> **Personal portfolio project, not intended for commercialization.** The
> code is under the MIT license (see [License](#license)), but the intent
> stays educational — not a commercial product.

---

## Table of Contents

- [About](#about)
- [Features](#features)
- [What data gets collected?](#what-data-gets-collected)
- [Data pipeline](#data-pipeline)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Environment variables](#environment-variables)
- [Using the app](#using-the-app)
  - [🏠 Home](#-home)
  - [🔍 Explore](#-explore)
  - [🕷️ Scraper](#️-scraper)
  - [❓ Help](#-help)
- [Data quality agent](#data-quality-agent)
- [Development](#development)
- [Project status](#project-status)
  - [Next steps](#next-steps)
- [Contributing](#contributing)
- [Support the project](#support-the-project)
- [Acknowledgments](#acknowledgments)
- [License](#license)

## About

**PickMySupplier** is a Streamlit app that scrapes a B2B marketplace
(products + suppliers), validates each row with a deterministic quality
agent, stores it in a SQLite database, then lets you explore it through
**natural-language search** and **charts** — like a buyer comparing
hundreds of suppliers without opening a single extra tab.

This project is the direct heir of [`Alibaba-CLI-Scraper`](https://github.com/poneoneo/Alibaba-CLI-Scraper)
(alias `aba_cli_scrapper` —
![GitHub Repo stars](https://img.shields.io/github/stars/poneoneo/Alibaba-CLI-Scraper?style=flat&label=%E2%98%85)),
rethought and improved on several fronts:

- a **single Streamlit interface** replaces the old CLI (Typer/Click)
  + MCP server + TUI trio — simpler to maintain, faster to pick up;
- natural-language search no longer runs code generated on the fly
  by an LLM (`datahorse`/`df.chat()`) — it produces a small structured
  spec (filters/sort/columns) executed ourselves with pandas,
  deterministically and with no risk of arbitrary execution;
- a **deterministic data quality agent** validates every row
  before insertion (no judgment left to an LLM);
- charts moved from Plotly to **ECharts**, with a consistent dark
  theme across the whole app;
- falls back to a demo dataset if live scraping breaks.

More improvements are planned (see [Project status](#project-status)).

The previous project taught me a lot, and I had a lot of fun building
it — this one is its logical continuation.

## Features

- **Scraping via ScrapingBee** (REST API, server-side JS rendering, free
  BYO key) — with a clear message if the quota/key is an issue.
- **Raw data export to CSV**, directly from the Explore page,
  for each dataset.
- **Natural-language search with no arbitrary code execution**: the
  question is turned by an LLM (Groq, JSON mode) into a small
  structured spec (`filters`, `sort`, `columns`), executed ourselves with pandas
  — never AI-generated code run blindly on the data.
- **ECharts charts**: histogram, bar, box plot, scatter plot,
  world map — automatic chart-type selection based on the question
  asked (or manual choice).
- **Deterministic data quality agent** (`data_quality.py`): no
  decision made by an LLM — a faulty row is rejected, the rest of the
  batch stays clean. Detailed report shown after every scrape.
- **Automatic summarization of product names** that are too long (marketing
  titles) via Groq, with a deterministic offline fallback if the call fails.
- **Built-in demo dataset** (deterministic, fixed seed) that goes through
  exactly the same pipeline as a real scrape — to explore the app without
  depending on the target site's availability.
- **One database per search**: two different searches never
  mix their results, dataset selector in the interface.
- **"Bring your own key" ScrapingBee key**: uses the site's demo key
  by default, or your own — with a step-by-step guide on the Help page to
  get one for free.

## What data gets collected?

Fields related to **suppliers** (`Supplier`):

| Field | Type | Description |
|---|---|---|
| `name` | `str` | Supplier name (unique) |
| `verification_mode` | `str` | Verification mode (e.g. `verified`/`unverified`) |
| `sopi_level` | `int` | Performance level |
| `country_name` | `str` | Supplier's country |
| `years_as_gold_supplier` | `int` | Years as a Gold Supplier |
| `supplier_service_score` | `float` | Service rating |

Fields related to **products** (`Product`):

| Field | Type | Description |
|---|---|---|
| `name` | `str` | Full product name (unique **per supplier**) |
| `short_name` | `str \| None` | Shortened version of the name, AI-generated |
| `alibaba_guranteed` | `bool` | Covered by Trade Assurance *(name kept as-is on purpose, to stay consistent with the model and the insertion code)* |
| `certifications` | `str` | Listed certifications |
| `minimum_to_order` | `int` | Minimum order quantity (MOQ) |
| `ordered_or_sold` | `int` | Number of orders/sales |
| `supplier_id` | `int` | Foreign key to the supplier |
| `min_price` / `max_price` | `float` | Price range |
| `product_score` | `float` | Product rating |
| `review_count` / `review_score` | `float` | Number of reviews and average rating |
| `shipping_time_score` | `float` | Shipping time rating |
| `is_full_promotion` | `bool` | On promotion |
| `is_customizable` | `bool` | Customizable |
| `is_instant_order` | `bool` | Instant order available |
| `trade_product` | `bool` | Covered by Trade Assurance |

Full models: [`sourcing_intel_cli/models.py`](sourcing_intel_cli/models.py).

## Data pipeline

```
1. proxies_providers.py   → scrapes raw HTML pages (ScrapingBee)
2. html_to_disk.py        → saves them to disk (scraped_pages/<keywords>/)
3. scrape_from_disk.py    → re-reads the HTML, extracts the embedded JSON → SupplierDict/ProductDict
4. data_quality.py        → validates each row (rejects the faulty row, keeps the rest)
5. engine_and_database.py → inserts the clean rows (rollback + skip on duplicate)
6. app.py                 → read-only access for charts and NL search
```

## Prerequisites

- Python 3.12 or higher
- A [Groq](https://console.groq.com) API key (free) for natural-language
  search and product name summarization
- A [ScrapingBee](https://www.scrapingbee.com) API key (free plan
  available — see the app's **Help** page for a step-by-step guide) for
  scraping

## Installation

```bash
git clone https://github.com/poneoneo/pickmysupplier.git
cd pickmysupplier
pip install -r requirements.txt
streamlit run app.py
```

The app isn't distributed as a package (no PyPI/pipx) — it's a
portfolio project meant to run locally, not a tool to install
globally.

## Environment variables

`.env` file at the project root, not committed (see `.gitignore`):

```
SCRAPINGBEE_API_KEY=
GROQ_API_KEY=
LOGURU_LEVEL=CRITICAL
```

On a hosting platform without a `.env` file (e.g. Streamlit Community
Cloud), both API keys can also be provided through the platform's own
secrets (`st.secrets`).

## Using the app

The app is multi-page via `st.navigation` — four pages accessible from
the sidebar.

### 🏠 Home

Project pitch, warning banner if the ScrapingBee key's quota (demo
or personal) is exhausted, quick links to the other three pages.

### 🔍 Explore

Pick a dataset (one database per past search, including the
demo), with a button to download that raw dataset as CSV, then
two tabs:

- **Natural-language search** — ask a question in plain English
  (e.g. *"what are the 5 best-rated suppliers in China?"*).
  The question is turned into a structured filter/sort executed by pandas,
  never into AI-generated code. Manual or automatic chart-type choice
  (histogram, bar, box plot, scatter plot,
  world map, or table only).
- **Charts** — price distribution, top 10 suppliers by service
  score, price spread by supplier country.

### 🕷️ Scraper

Launches a live scrape (keywords + number of pages) via ScrapingBee,
with an optional field to use your own key.
A **"Load the demo dataset"** button lets you explore the app
without depending on the target site's availability (structure that can
change). Every scrape (or demo load) goes through the same quality
validation pipeline, with a report shown right after.

### ❓ Help

Onboarding guide: how to get a free ScrapingBee key step by
step, how the data is organized (one database per search), and a
condensed how-to (live scraping vs. demo, asking a question, reading the
charts).

## Data quality agent

**Deterministic** rules, no LLM judgment (`sourcing_intel_cli/data_quality.py`):

- **Suppliers**: non-empty and unique name within the batch; `sopi_level`
  a non-negative integer; `supplier_service_score` a non-negative number;
  `years_as_gold_supplier` convertible to a non-negative integer.
- **Products**: non-empty name, unique **per supplier**; `supplier_id`
  must match an already-validated supplier; `min_price <= max_price`,
  both non-negative; all boolean fields strictly `bool`; all
  numeric fields non-negative.

A faulty row is rejected, the rest of the batch is kept — a deliberate
policy, so a single malformed row never costs an entire scrape.

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest --cov=sourcing_intel_cli   # tests + coverage
python -m ruff check .                       # lint
```

**Always `python -m pytest` / `python -m ruff check .`**, never bare
`pytest`/`ruff` — the package isn't installed (no `pip install -e .`),
so only `python -m` adds the current directory to `sys.path`.

CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs lint +
tests + coverage on every push/PR to `main`, and uploads coverage to
[Codecov](https://codecov.io/gh/poneoneo/pickmysupplier) (badge at the top
of this README).

## Project status

- **No formal versioning yet** (no tags/releases, no automated
  changelog) — Commitizen and pipx packaging were considered
  then explicitly deferred; the project is currently tracked
  only through Git history and Pull Requests.
- Live scraping and natural-language search have been validated with
  real calls; the rest (rendering charts with large real-world
  volumes, etc.) hasn't been tested under real conditions beyond
  everyday usage yet.

### Next steps

- **Public hosting**: deployed on Streamlit Community Cloud, but the app
  is currently restricted to specific viewers rather than public — see
  the app's sharing settings on Streamlit Cloud to open it up.
- Automated versioning/changelog (Commitizen), pipx packaging, and
  further iterations on data quality and charts as usage grows.

✅ Already done: raw data export to CSV, removal of BrightData
(ScrapingBee is now the only proxy provider).

**Got an idea to make this more useful?** Open an
[issue](https://github.com/poneoneo/pickmysupplier/issues/new) to
suggest what you'd like to see implemented.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the commit (Gitmoji)
and branch naming convention used on this project — it applies to all
commits, including the primary author's.

## Support the project

If this tool has been useful to you or you appreciate the work,
[☕ a coffee on Ko-fi](https://ko-fi.com/poneoneo) is always appreciated.

## Acknowledgments

Thanks to [DataHorse](https://github.com/DeDolphins/DataHorse), used in
an earlier version of the natural-language search (see
[Features](#features)) and since replaced by a homegrown approach.
It's no longer in the code today, but it's what made this project
possible in the first place.

## License

This project is licensed under [MIT](LICENSE).
