"""PickMySupplier — multi-page Streamlit app: scrape, validate, browse, and
ask natural-language questions about product/supplier data.

Four pages via st.navigation: Accueil (landing), Explorer (dataset picker +
NL search + charts), Scraper (live scraping + demo data), Aide (onboarding
guide). Replaces the old CLI (commands.py) and MCP server (mcp_server.py).
Run with: streamlit run app.py
"""

from __future__ import annotations

import json
import uuid
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
	build_map_option,
	build_scatter_option,
	suggest_chart_type,
)
from sourcing_intel_cli.data_quality import (
	run_quality_checks,
	write_quality_report,
)
from sourcing_intel_cli.datasets import (
	DB_PREFIX,
	cleanup_stale_sessions,
	dataset_label,
	discover_databases,
	slugify,
)
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
# Session identity
# ---------------------------------------------------------------------------


def _get_session_id() -> str:
	"""Stable per-visit identifier used to namespace a visitor's scraped data.

	Generated once per Streamlit session and cached in `st.session_state` —
	scraped HTML and per-search databases are stored under
	`sessions/<session_id>/` so one visitor never sees another's data (see
	docs/superpowers/specs/2026-09-05-session-scoped-data-isolation-design.md).

	:return: A short hex id, stable for the lifetime of this browser session.
	:rtype: str
	"""
	return st.session_state.setdefault("session_id", uuid.uuid4().hex[:12])


# ---------------------------------------------------------------------------
# Data access (read-only for the search/charts section)
# ---------------------------------------------------------------------------


@st.cache_data
def load_products_with_suppliers(db_path: Path) -> pd.DataFrame:
	"""Read products joined with suppliers from the given SQLite DB.

	Read-only: a plain SELECT via pandas, never a write path. This is what
	backs both the charts and the natural-language search — the same
	structural guarantee the old CSV-only ai-agent had (no direct DB access
	from a natural-language query), just without the extra CSV export step.

	Cached by `db_path` — `page_explorer()` calls this on every rerun
	(every widget interaction on the page, not just on dataset switch), so
	without caching a single search's whole table gets re-read from disk on
	every keystroke in the NL search box. `_validate_and_insert` calls
	`st.cache_data.clear()` after every write, so a re-scrape of the same
	keywords (same `db_path`) can't serve stale cached rows.

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
      Product.alibaba_guranteed as alibaba_guranteed,
      Product.certifications as certifications,
      Product.ordered_or_sold as ordered_or_sold,
      Product.shipping_time_score as shipping_time_score,
      Product.is_full_promotion as is_full_promotion,
      Product.is_customizable as is_customizable,
      Product.is_instant_order as is_instant_order,
      Supplier.name as supplier_name,
      Supplier.country_name as country_name,
      Supplier.sopi_level as sopi_level,
      Supplier.years_as_gold_supplier as years_as_gold_supplier,
      Supplier.supplier_service_score as supplier_service_score,
      Supplier.verification_mode as verification_mode
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
	raw_suppliers: list[SupplierDict],
	raw_products: list[ProductDict],
	db_name: str,
	report_path: str | None = None,
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
	:param report_path: Where to write the quality report JSON. `None` (the
		default, used by the demo dataset loader — non-sensitive, shared data)
		keeps `write_quality_report`'s own default, a single shared
		`data_quality_report.json` at the project root. The live-scrape call
		site passes a `sessions/<session_id>/...` path instead, since that
		file is otherwise the last scrape-derived artifact written outside a
		visitor's own session directory.
	:type report_path: str | None
	"""
	with st.spinner("Running data quality checks..."):
		suppliers, products, issues = run_quality_checks(raw_suppliers, raw_products)
		if report_path:
			Path(report_path).parent.mkdir(parents=True, exist_ok=True)
			write_quality_report(issues, path=report_path)
		else:
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
		st.warning(
			"⚠️ Your ScrapingBee key isn't working (out of credits, "
			"or invalid/expired) — check your ScrapingBee account or try again later."
		)
	st.caption(
		"There's no shared scraping key on this site — grab your own free "
		"ScrapingBee key (2 minutes) on the **Scraper** page before your "
		"first search."
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
	session_id = _get_session_id()
	databases = discover_databases(root=Path(f"sessions/{session_id}/db"))
	demo_db = Path(f"{DB_PREFIX}_demo.sqlite")
	demo_db_exists = demo_db.exists()

	if not databases and not demo_db_exists:
		st.info("No data yet — go to the **Scraper** page to launch a scrape.")
		return

	# The shared demo dataset gets its own distinct label, built directly
	# rather than via `dataset_label(demo_db)` — that would just return
	# "demo", which collides with (and, since it's added last, silently
	# overwrites in this dict) a visitor's own session-scoped search for the
	# literal keyword "demo".
	dataset_labels = {dataset_label(p): p for p in databases}
	if demo_db_exists:
		dataset_labels["demo (shared)"] = demo_db
	selected_label = st.selectbox(
		"Dataset to explore",
		list(dataset_labels.keys()),
		help="Each search has its own database — choose which one to explore.",
	)
	df = load_products_with_suppliers(dataset_labels[selected_label])

	if df.empty:
		st.info("This dataset is empty.")
		return

	# Used to make the example questions below reflect what's actually in
	# this dataset instead of a hardcoded country that might not appear in
	# it at all (e.g. a "wireless earbuds" scrape with no Chinese supplier).
	present_countries = df["country_name"].dropna()
	example_country = (
		present_countries.value_counts().index[0] if not present_countries.empty else "China"
	)

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
					- `alibaba_guranteed` — covered by the marketplace's own guarantee (true/false)
					- `certifications` — certifications the product holds
					- `ordered_or_sold` — units already ordered/sold
					- `shipping_time_score` — shipping speed rating
					- `is_full_promotion` / `is_customizable` / `is_instant_order` — true/false flags
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
					- `verification_mode` — how the supplier was verified
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
			f"""
			- *Which 5 suppliers have the best supplier_service_score?* (Bar)
			- *What is the distribution of minimum prices?* (Histogram)
			- *What is the spread of product_score by supplier country?* (Box plot)
			- *Is there a correlation between product_score and min_price?* (Scatter)
			- *Compare the average product price by supplier country.* (Bar)
			- *What is the distribution of MOQ (minimum order quantity)?* (Histogram)
			- *Which countries are represented among the suppliers?* (World map)
			- *List suppliers in {example_country} with at least 5 years as a Gold Supplier, sorted by minimum price.* (Table — pick "Table only" from the menu, "Auto" doesn't detect this case and will show a bar chart by default)
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

		col3, col4 = st.columns(2)
		with col3:
			option_reliability = build_scatter_option(
				df, "review_count", "review_score", "Review score vs. number of reviews"
			)
			st_echarts(options=option_reliability, theme="dark", height="500px")
		with col4:
			trade_coverage = (
				df.groupby("country_name")["trade_product"]
				.mean()
				.mul(100)
				.sort_values(ascending=False)
				.head(10)
				.reset_index()
			)
			option_trade = build_bar_option(
				trade_coverage,
				"country_name",
				"trade_product",
				"Trade Assurance coverage by country (%)",
				horizontal=True,
			)
			st_echarts(options=option_trade, theme="dark", height="500px")

		# One row per supplier, not per product — value_counts() in
		# build_map_option would otherwise count a supplier once per product
		# they list, inflating countries with a few prolific suppliers.
		supplier_counts = df.drop_duplicates("supplier_name")
		option_map = build_map_option(supplier_counts, "country_name", "Suppliers by country")
		st_echarts(
			options=option_map,
			theme="dark",
			height="500px",
			map=Map("world", _load_world_geojson()),
		)


def page_scraper() -> None:
	"""Live scraping controls, demo dataset loader, and the required ScrapingBee key field."""
	st.title("Scraper")

	if st.session_state.get("sb_quota_exhausted"):
		st.warning(
			"⚠️ Your ScrapingBee key isn't working (out of credits, "
			"or invalid/expired) — check your ScrapingBee account or try again later."
		)

	st.subheader("1. Get your free ScrapingBee key")
	st.caption(
		"There's no shared key on this site — each visitor scrapes with "
		"their own free ScrapingBee account, so your searches never "
		"compete with anyone else's quota."
	)
	st.link_button("Get a free key at scrapingbee.com →", "https://www.scrapingbee.com")
	user_scrapingbee_key = st.text_input(
		"Your ScrapingBee key",
		type="password",
		help="See the Help page for step-by-step instructions to find it, for free.",
		key="user_scrapingbee_key",
	)

	st.subheader("2. Scrape")
	keywords = st.text_input("Keywords", placeholder="e.g. wireless earbuds")
	page_results = st.number_input("Number of pages", min_value=1, max_value=50, value=5)

	if not user_scrapingbee_key:
		st.caption("⚠️ Enter your ScrapingBee key above to enable scraping.")

	if st.button(
		"Scrape live", type="primary", disabled=not keywords or not user_scrapingbee_key
	):
		session_id = _get_session_id()
		slug = slugify(keywords)
		save_in_folder = f"sessions/{session_id}/scraped_pages/{slug}"

		with st.spinner("Scraping in progress (can take several minutes)..."):
			try:
				ScrapingBeeProxyProvider.sync_scraper(
					save_in=save_in_folder,
					key_words=keywords,
					page_results=int(page_results),
					api_key=user_scrapingbee_key or None,
				)
				# A prior failed attempt (this session) may have latched
				# sb_quota_exhausted on — clear it now that a scrape with
				# this key actually went through, so the warning banner
				# doesn't keep showing on every page after the key is fixed.
				st.session_state["sb_quota_exhausted"] = False
			except ScrapingBeeKeyError as e:
				logger.warning(f"ScrapingBee key problem: {e}")
				st.session_state["sb_quota_exhausted"] = True
				st.error(
					"Your ScrapingBee key isn't working (out of credits, or "
					"invalid/expired). Check your ScrapingBee account or try again later."
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

		_validate_and_insert(
			raw_suppliers,
			raw_products,
			db_name=f"sessions/{session_id}/db/{DB_PREFIX}_{slug}",
			report_path=f"sessions/{session_id}/data_quality_report.json",
		)

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

	st.header("1. Get your free ScrapingBee key")
	st.markdown(
		"""
		There's no shared scraping key on this site — every visitor needs
		their own, free ScrapingBee account. It's the first step, before
		you can run any live search:

		1. Go to [scrapingbee.com](https://www.scrapingbee.com) and create a
		   free account (email + password, or via Google/GitHub).
		2. Once logged in, your dashboard shows your API key at the
		   top of the page, under **API Key** — copy it with the icon next to it.
		3. The free plan includes a number of trial credits (check the
		   exact amount on their pricing page, it can change) —
		   plenty to test this app.
		4. Come back to the **Scraper** page on this site and paste your key into the
		   *"Your ScrapingBee key"* field — the *"Scrape live"* button
		   stays disabled until you do.
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

		**Your data only lasts for this browser session.** Refreshing the
		page or coming back later starts a new session, and your previous
		searches won't show up in the selector anymore — re-run the scrape
		if you need that data again. Session data is also automatically
		deleted from the server after 48 hours, whether you're still around
		or not.
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
		describe what you're looking for in a sentence. The question is
		turned into a deterministic filter/sort, never into AI-generated
		code run blindly. A few examples of what you can ask:
		- *"the 5 best-rated suppliers in China"*
		- *"products with a review score above 4.5 but fewer than 10
		  reviews"* — high score, barely any votes, worth a second look
		- *"suppliers in China with Trade Assurance"*
		- *"products that support instant order and are customizable"*
		- *"the cheapest products with more than 100 units already sold"*

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


@st.cache_resource(ttl=3600)
def _cleanup_stale_sessions_once() -> None:
	"""Run `cleanup_stale_sessions` at most once per hour across all visitors.

	`st.cache_resource` caches at the process level (shared by every
	visitor, unlike `st.session_state`) — with a 1-hour TTL this runs the
	disk housekeeping once per hour for the whole site, no matter how many
	concurrent sessions there are, without a separate scheduler.

	Note `st.cache_resource` does NOT cache an exception raised by the
	wrapped function — it would just re-raise on every rerun, for every
	visitor, turning this best-effort housekeeping into a permanent outage.
	`cleanup_stale_sessions` already tolerates the individual filesystem
	errors it can hit, but this `try/except` is defense in depth on top of
	that: best-effort housekeeping must never be able to take the app down.

	:return: None
	:rtype: None
	"""
	try:
		cleanup_stale_sessions()
	except Exception as e:  # noqa: BLE001
		logger.warning(f"Stale-session cleanup failed, continuing without it: {e}")


_cleanup_stale_sessions_once()

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
