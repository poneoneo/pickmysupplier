"""PickMySupplier — multi-page Streamlit app: scrape, validate, browse, and
ask natural-language questions about product/supplier data.

Four pages via st.navigation: Accueil (landing), Explorer (dataset picker +
NL search + charts), Scraper (live scraping + demo data), Aide (onboarding
guide). Replaces the old CLI (commands.py) and MCP server (mcp_server.py).
Run with: streamlit run app.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st
from loguru import logger
from sqlmodel import SQLModel
from streamlit_echarts import Map, st_echarts

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
from sourcing_intel_cli.proxies_providers import ScrapingBeeProxyProvider, ScrapingBeeKeyError
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
      Product.minimum_to_order as minimum_to_order,
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


@st.cache_resource
def _load_world_geojson() -> dict:
	"""Load the world map GeoJSON used by the "map" chart type, once per session.

	~1MB of polygon data — cached so it's read from disk once, not on every
	Streamlit rerun. Sourced from Apache ECharts' own map examples (see
	`sourcing_intel_cli/chart_builder.py`'s `build_map_option` docstring for
	why the region names are English while this project's data is French).

	:return: The parsed GeoJSON `FeatureCollection`.
	:rtype: dict
	"""
	path = Path(__file__).parent / "sourcing_intel_cli" / "world_map.json"
	with open(path, encoding="utf-8") as f:
		return json.load(f)


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
	with st.spinner("Running data quality checks..."):
		suppliers, products, issues = run_quality_checks(raw_suppliers, raw_products)
		write_quality_report(issues)

	if issues:
		st.warning(f"{len(issues)} row(s) rejected by the quality agent — see details below.")
		with st.expander("Rejection details"):
			st.dataframe(
				pd.DataFrame(
					[
						{"entity": i.entity, "id": i.identifier, "field": i.field, "reason": i.reason}
						for i in issues
					]
				)
			)
	else:
		st.success("No quality issues detected.")

	if not suppliers and not products:
		st.error("Everything was rejected, nothing to insert.")
		st.stop()

	if products:
		with st.spinner("Summarizing product names that are too long..."):
			short_names = summarize_product_names([p["name"] for p in products])
			for product in products:
				product["short_name"] = short_names[product["name"]]

	with st.spinner("Writing to the database..."):
		try:
			engine = create_db_engine(db_name=db_name)
			save_all_changes(engine_db=engine, sql_model=SQLModel)
			add_suppliers_to_db(suppliers=suppliers, engine_db=engine)
			add_products_to_db(products=products, engine_db=engine)
		except Exception as e:  # noqa: BLE001
			logger.exception("Database write failed")
			st.error(f"The database write failed: {e}\n\nSee logs/app.log for details.")
			st.stop()

	st.success(f"{len(suppliers)} supplier(s) and {len(products)} product(s) added.")
	st.cache_data.clear()


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


def page_accueil() -> None:
	"""Landing page: pitch, quota banner, links to the other pages."""
	st.title("🤏🛒 PickMySupplier")
	st.markdown(
		"""
		**PickMySupplier** scrapes a B2B marketplace, validates and stores
		the data, then lets you explore it through natural-language search
		and charts — like a buyer comparing hundreds of suppliers without
		opening a single extra tab.

		Portfolio project, for educational purposes — not a commercial product.
		"""
	)
	if st.session_state.get("sb_quota_exhausted"):
		if st.session_state.get("sb_quota_exhausted_own_key"):
			st.warning(
				"⚠️ Your ScrapingBee key isn't working (out of credits, "
				"or invalid/expired) — check your ScrapingBee account or try again later."
			)
		else:
			st.warning(
				"⚠️ The demo ScrapingBee key isn't working right now "
				"(out of credits or expired) — get your own for free, "
				"see the **Help** page."
			)
	st.markdown("**To get started:**")
	col_explorer, col_scraper, col_aide = st.columns(3)
	with col_explorer:
		st.page_link(PAGE_EXPLORER, label="Explore the data")
	with col_scraper:
		st.page_link(PAGE_SCRAPER, label="Start a scrape")
	with col_aide:
		st.page_link(PAGE_AIDE, label="Usage guide")


def page_explorer() -> None:
	"""Dataset picker + natural-language search + charts."""
	st.title("Explore")
	databases = discover_databases()

	if not databases:
		st.info("No data yet — go to the **Scraper** page to launch a scrape.")
		return

	dataset_labels = {dataset_label(p): p for p in databases}
	selected_label = st.selectbox(
		"Dataset to explore",
		list(dataset_labels.keys()),
		help="Each search has its own database — choose which one to explore.",
	)
	df = load_products_with_suppliers(dataset_labels[selected_label])

	if df.empty:
		st.info("This dataset is empty.")
		return

	st.download_button(
		"⬇️ Download this dataset (CSV)",
		data=df.to_csv(index=False).encode("utf-8"),
		file_name=f"{selected_label}.csv",
		mime="text/csv",
		help="The raw dataset shown below — products joined to their supplier.",
	)

	tab_search, tab_charts = st.tabs(["💬 Natural-language search", "📊 Charts"])

	with tab_search:
		st.info(
			"🧑‍💼 **Put yourself in the shoes of an entrepreneur who wants to source a "
			"product on Alibaba.** You have hundreds of suppliers in front of you, all with "
			"different prices, ratings, and guarantees — you want to find the best "
			"suppliers, at the best price, without spending hours comparing rows by hand. "
			"That's exactly what this search does: ask your question in plain language, "
			"it filters/sorts the data for you."
		)

		with st.expander("📋 Available fields in the data"):
			col_product, col_supplier = st.columns(2)
			with col_product:
				st.markdown(
					"""
					**Product**
					- `product_name` — full product name (sometimes long)
					- `short_name` — shortened version, more readable in a table/chart
					- `min_price` / `max_price` — price range (USD)
					- `minimum_to_order` — minimum order quantity (MOQ)
					- `product_score` — product rating (out of 5)
					- `review_count` / `review_score` — number of reviews and average rating
					- `trade_product` — covered by Trade Assurance (true/false)
					"""
				)
			with col_supplier:
				st.markdown(
					"""
					**Supplier**
					- `supplier_name` — supplier name
					- `country_name` — supplier's country
					- `sopi_level` — performance level (1 to 5)
					- `years_as_gold_supplier` — years as a Gold Supplier
					- `supplier_service_score` — service rating (out of 5)
					"""
				)
			st.caption(
				"Each row = one product linked to its supplier — you can combine "
				"criteria from both sides in the same question."
			)

		st.markdown(
			"**Example questions to ask** — the chart in parentheses is the one "
			"\"Auto\" actually picks for this phrasing (verified, not just indicative):"
		)
		st.markdown(
			"""
			- *Which 5 suppliers have the best supplier_service_score?* (Bar)
			- *What is the distribution of minimum prices?* (Histogram)
			- *What is the spread of product_score by supplier country?* (Box plot)
			- *Is there a correlation between product_score and min_price?* (Scatter)
			- *Compare the average product price by supplier country.* (Bar)
			- *What is the distribution of MOQ (minimum order quantity)?* (Histogram)
			- *Which countries are represented among the suppliers?* (World map)
			- *List suppliers in China with at least 5 years as a Gold Supplier, sorted by minimum price.* (Table — pick "Table only" from the menu, "Auto" doesn't detect this case and will show a bar chart by default)
			"""
		)

		query = st.text_input(
			"Ask your question about products/suppliers",
			placeholder="e.g. what are the 5 best-rated suppliers in China?",
		)
		chart_type_labels = {
			"Auto (based on the question)": "auto",
			"Table only": "none",
			"Histogram": "histogram",
			"Bar": "bar",
			"Box plot": "box",
			"Scatter": "scatter",
			"World map": "map",
		}
		chart_type_choice = st.selectbox("Chart type", list(chart_type_labels.keys()))

		if "nl_search_running" not in st.session_state:
			st.session_state["nl_search_running"] = False

		# Two-phase click handling: the click itself only sets a flag and
		# triggers an immediate rerun, which commits the flag to
		# session_state *before* the slow Groq call starts. A rapid second
		# click during that call finds the button already `disabled=True` on
		# render, instead of interrupting the in-flight rerun and silently
		# producing nothing (Streamlit cancels an in-progress run when a new
		# widget interaction arrives, so without this guard, rapid clicks
		# raced each other and only a click spaced out from the others ever
		# reached the chart-rendering code below).
		if st.button(
			"Search", disabled=(not query) or st.session_state["nl_search_running"]
		):
			st.session_state["nl_search_running"] = True
			st.rerun()

		if st.session_state["nl_search_running"]:
			with st.spinner("Searching..."):
				try:
					# The LLM only ever returns a small filter/sort/select spec — we
					# execute it ourselves with pandas. No LLM-generated code runs.
					spec = build_query_spec(query, df)
					result = apply_query_spec(df, spec)
				except RuntimeError as e:
					st.session_state["nl_search_running"] = False
					st.error(str(e))
					st.stop()
				except Exception:  # noqa: BLE001
					st.session_state["nl_search_running"] = False
					logger.exception("Natural-language search failed")
					st.error(
						"The search failed. Try rephrasing your question, "
						"or try again later if the problem persists."
					)
					st.stop()
			st.session_state["nl_search_running"] = False

			# A nonsense/off-topic question still gets syntactically valid
			# JSON back from Groq (JSON mode guarantees that, not semantic
			# relevance) — apply_query_spec then silently no-ops every
			# filter/column/sort that doesn't match a real column rather
			# than raising, so `result` ends up as the full, unfiltered
			# dataset instead of empty. Left unchecked, that used to reach
			# build_chart/st_echarts with no clear signal to the user that
			# their question wasn't understood — flagging it here instead.
			spec_is_empty = (
				not spec.get("filters")
				and not spec.get("columns")
				and spec.get("sort_by") not in df.columns
			)
			if spec_is_empty:
				st.info(
					"I didn't understand that question — try mentioning a "
					"specific criterion (price, score, country, supplier...)."
				)
			elif result.empty:
				st.warning("No results for this question.")
			else:
				chart_type = chart_type_labels[chart_type_choice]
				resolved_type = suggest_chart_type(query) if chart_type == "auto" else chart_type
				option = (
					build_chart(result, resolved_type, title=query, metric_col=spec.get("sort_by"))
					if resolved_type != "none"
					else None
				)
				if option is not None:
					# The map's GeoJSON is registered separately from the
					# option dict — st_echarts(map=...) is how ECharts
					# learns what "world" (referenced in
					# option["series"][0]["map"]) actually resolves to.
					map_arg = Map("world", _load_world_geojson()) if resolved_type == "map" else None
					st_echarts(options=option, theme="dark", height="500px", map=map_arg)
					with st.expander("View chart data"):
						st.dataframe(result, use_container_width=True)
				else:
					if resolved_type != "none":
						st.caption(
							f"Not enough suitable columns for a \"{resolved_type}\" chart "
							"with this result — showing a table instead."
						)
					st.dataframe(result, use_container_width=True)
		st.caption(
			"This search only reads an in-memory copy of the data (read-only) — "
			"never writes to the database from a natural-language query."
		)

	with tab_charts:
		col1, col2 = st.columns(2)
		with col1:
			option_price = build_histogram_option(df, "min_price", "Distribution of minimum prices")
			st_echarts(options=option_price, theme="dark", height="500px")
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
				"Top 10 suppliers by service score",
				horizontal=True,
			)
			st_echarts(options=option_suppliers, theme="dark", height="500px")

		option_country = build_box_option(
			df, "country_name", "min_price", "Price distribution by supplier country"
		)
		st_echarts(options=option_country, theme="dark", height="500px")


def page_scraper() -> None:
	"""Live scraping controls, demo dataset loader, and the ScrapingBee BYO-key field."""
	st.title("Scraper")

	if st.session_state.get("sb_quota_exhausted"):
		if st.session_state.get("sb_quota_exhausted_own_key"):
			st.warning(
				"⚠️ Your ScrapingBee key isn't working (out of credits, "
				"or invalid/expired) — check your ScrapingBee account or try again later."
			)
		else:
			st.warning(
				"⚠️ The demo ScrapingBee key isn't working right now "
				"(out of credits or expired) — get your own for free "
				"(see the **Help** page) or enter it below."
			)

	keywords = st.text_input("Keywords", placeholder="e.g. wireless earbuds")
	page_results = st.number_input("Number of pages", min_value=1, max_value=50, value=5)

	user_scrapingbee_key = st.text_input(
		"Your ScrapingBee key (optional)",
		type="password",
		help="Leave empty to use the site's demo key. See the "
		"Help page to find your own, for free.",
		key="user_scrapingbee_key",
	)

	if st.button("Scrape live", type="primary", disabled=not keywords):
		slug = slugify(keywords)
		save_in_folder = f"scraped_pages/{slug}"

		with st.spinner("Scraping in progress (can take several minutes)..."):
			try:
				ScrapingBeeProxyProvider.sync_scraper(
					save_in=save_in_folder,
					key_words=keywords,
					page_results=int(page_results),
					api_key=user_scrapingbee_key or None,
				)
			except ScrapingBeeKeyError as e:
				logger.warning(f"ScrapingBee key problem: {e}")
				st.session_state["sb_quota_exhausted"] = True
				st.session_state["sb_quota_exhausted_own_key"] = bool(user_scrapingbee_key)
				if user_scrapingbee_key:
					st.error(
						"Your ScrapingBee key isn't working (out of credits, or "
						"invalid/expired). Check your ScrapingBee account or try again later."
					)
				else:
					st.error(
						"The demo ScrapingBee key isn't working (out of credits or "
						"expired). Get your own for free (see the Help page) "
						"or enter it above."
					)
				st.stop()
			except Exception:  # noqa: BLE001
				logger.exception("Scraping failed")
				st.error("The scrape failed. See logs/app.log for details.")
				st.stop()

		with st.spinner("Analyzing pages..."):
			try:
				page_parser = PageParser(targeted_folder=save_in_folder)
				raw_suppliers = page_parser.detected_suppliers()
				raw_products = page_parser.detected_products()
			except Exception:  # noqa: BLE001
				logger.exception("Page parsing failed")
				st.error("Analyzing the scraped pages failed. See logs/app.log for details.")
				st.stop()

		_validate_and_insert(raw_suppliers, raw_products, db_name=f"{DB_PREFIX}_{slug}")

	st.divider()
	st.caption(
		"The target site sometimes changes structure and can break live "
		"scraping — use the demo dataset to explore the app without depending on the site."
	)
	if st.button("Load the demo dataset"):
		raw_suppliers, raw_products = generate_demo_data()
		_validate_and_insert(raw_suppliers, raw_products, db_name=f"{DB_PREFIX}_demo")


def page_aide() -> None:
	"""Onboarding guide: free ScrapingBee key, data architecture, how to use the app."""
	st.title("❓ Help")

	st.header("1. Get a free ScrapingBee key")
	st.markdown(
		"""
		1. Go to [scrapingbee.com](https://www.scrapingbee.com) and create a
		   free account (email + password, or via Google/GitHub).
		2. Once logged in, your dashboard shows your API key at the
		   top of the page, under **API Key** — copy it with the icon next to it.
		3. The free plan includes a number of trial credits (check the
		   exact amount on their pricing page, it can change) —
		   plenty to test this app.
		4. Come back to the **Scraper** page on this site and paste your key into the
		   *"Your ScrapingBee key (optional)"* field.
		"""
	)

	st.header("2. How the data is organized")
	st.markdown(
		"""
		Every search you run (a set of keywords) creates its **own
		database** — a separate file, named after your search.
		Results from two different searches never mix.

		On the **Explore** page, the *"Dataset to
		explore"* selector lets you pick which of your past searches
		to look at — including the demo dataset.
		"""
	)

	st.header("3. How to use it")
	st.markdown(
		"""
		**Live scraping vs. demo dataset** — live scraping depends
		on the target site's structure, which changes sometimes; if it breaks,
		use the *"Load the demo dataset"* button on the
		**Scraper** page to explore the app without depending on the site.

		**Asking a natural-language question** — on the **Explore** page,
		describe what you're looking for in a sentence (e.g. *"the 5
		best-rated suppliers in China"*). The question is turned into a
		deterministic filter/sort, never into AI-generated code run blindly.

		**Reading the charts** — a histogram shows a distribution
		(e.g. price spread), a bar chart compares
		categories (e.g. top suppliers), a box plot shows the
		spread of prices by group (e.g. by country), a scatter plot
		shows a relationship between two numeric values.
		"""
	)


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

st.set_page_config(page_title="PickMySupplier", page_icon="🤏🛒", layout="wide")

PAGE_ACCUEIL = st.Page(page_accueil, title="Home", icon="🏠", default=True)
PAGE_EXPLORER = st.Page(page_explorer, title="Explore", icon="🔍")
PAGE_SCRAPER = st.Page(page_scraper, title="Scraper", icon="🕷️")
PAGE_AIDE = st.Page(page_aide, title="Help", icon="❓")

st.sidebar.markdown("## 🤏🛒 PickMySupplier")

pg = st.navigation([PAGE_ACCUEIL, PAGE_EXPLORER, PAGE_SCRAPER, PAGE_AIDE])

st.sidebar.link_button(
	"☕ Support on Ko-fi", "https://ko-fi.com/poneoneo", use_container_width=True
)

pg.run()
