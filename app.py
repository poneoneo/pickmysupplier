"""Sourcing Intel — single-page Streamlit app: scrape, validate, browse, and
ask natural-language questions about product/supplier data.

Replaces the old CLI (commands.py) and MCP server (mcp_server.py): everything
happens in-browser now. Run with: streamlit run app.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
from loguru import logger
from sqlmodel import SQLModel

from sourcing_intel_cli.data_quality import (
	run_quality_checks,
	write_quality_report,
)
from sourcing_intel_cli.demo_data import generate_demo_data
from sourcing_intel_cli.engine_and_database import (
	add_products_to_db,
	add_suppliers_to_db,
	create_db_engine,
	save_all_changes,
)
from sourcing_intel_cli.proxies_providers import BrightDataProxyProvider, ScrapingBeeProxyProvider
from sourcing_intel_cli.scrape_from_disk import PageParser
from sourcing_intel_cli.typed_datas import ProductDict, SupplierDict

DB_FILE = "sourcing_intel"  # -> sourcing_intel.sqlite

st.set_page_config(page_title="Sourcing Intel", layout="wide")


# ---------------------------------------------------------------------------
# Data access (read-only for the search/charts section)
# ---------------------------------------------------------------------------


def load_products_with_suppliers() -> pd.DataFrame:
	"""Read products joined with suppliers from the local SQLite DB.

	Read-only: a plain SELECT via pandas, never a write path. This is what
	backs both the charts and the natural-language search — the same
	structural guarantee the old CSV-only ai-agent had (no direct DB access
	from a natural-language query), just without the extra CSV export step.

	:return: DataFrame with one row per product, joined to its supplier. Empty
		DataFrame if the database doesn't exist yet.
	"""
	db_path = Path(f"{DB_FILE}.sqlite")
	if not db_path.exists():
		return pd.DataFrame()

	import sqlite3

	query = """
      SELECT Product.name as product_name,
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


# ---------------------------------------------------------------------------
# Sidebar: scraping + DB update
# ---------------------------------------------------------------------------


def _validate_and_insert(
	raw_suppliers: list[SupplierDict], raw_products: list[ProductDict]
) -> None:
	"""Run the quality agent then write clean rows to the DB, with Streamlit feedback.

	Shared by the live scraper and the demo dataset loader so both sources go
	through the exact same validation/insertion path.

	:param raw_suppliers: Suppliers straight from the source (scraper or demo data).
	:param raw_products: Products straight from the source (scraper or demo data).
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

	with st.spinner("Écriture en base..."):
		try:
			engine = create_db_engine(db_name=DB_FILE)
			save_all_changes(engine_db=engine, sql_model=SQLModel)
			add_suppliers_to_db(suppliers=suppliers, engine_db=engine)
			add_products_to_db(products=products, engine_db=engine)
		except Exception as e:  # noqa: BLE001
			st.error(f"L'écriture en base a échoué : {e}")
			st.stop()

	st.success(f"{len(suppliers)} fournisseur(s) et {len(products)} produit(s) ajoutés.")
	st.cache_data.clear()


with st.sidebar:
	st.header("Scraper")
	keywords = st.text_input("Mots-clés", placeholder="ex: wireless earbuds")
	provider_name = st.selectbox("Fournisseur de proxy", ["scrapingbee", "brightdata"])
	page_results = st.number_input("Nombre de pages", min_value=1, max_value=50, value=5)

	if st.button("Scraper en direct", type="primary", disabled=not keywords):
		provider_cls = {
			"brightdata": BrightDataProxyProvider,
			"scrapingbee": ScrapingBeeProxyProvider,
		}[provider_name]
		save_in_folder = f"scraped_pages/{keywords.strip().replace(' ', '_')}"

		with st.spinner("Scraping en cours (peut prendre plusieurs minutes)..."):
			try:
				provider_cls.sync_scraper(
					save_in=save_in_folder, key_words=keywords, page_results=int(page_results)
				)
			except Exception as e:  # noqa: BLE001
				st.error(f"Le scraping a échoué : {e}")
				st.stop()

		with st.spinner("Analyse des pages..."):
			page_parser = PageParser(targeted_folder=save_in_folder)
			raw_suppliers = page_parser.detected_suppliers()
			raw_products = page_parser.detected_products()

		_validate_and_insert(raw_suppliers, raw_products)

	st.divider()
	st.caption(
		"Le site cible change parfois de structure et peut casser le scraping en "
		"direct — utilise le jeu de démo pour explorer l'app sans dépendre du site."
	)
	if st.button("Charger le jeu de données de démo"):
		raw_suppliers, raw_products = generate_demo_data()
		_validate_and_insert(raw_suppliers, raw_products)


# ---------------------------------------------------------------------------
# Main area: search + charts
# ---------------------------------------------------------------------------

st.title("🔍 Sourcing Intel")

df = load_products_with_suppliers()

if df.empty:
	st.info("Aucune donnée pour l'instant — lance un scraping depuis la barre latérale.")
else:
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
					- `product_name` — nom du produit
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
		if st.button("Chercher", disabled=not query):
			import datahorse  # noqa: F401 — import registers df.chat() as a pandas accessor

			from sourcing_intel_cli.nl_search import configure_datahorse

			with st.spinner("Recherche en cours..."):
				try:
					configure_datahorse()
				except RuntimeError as e:
					st.error(str(e))
					st.stop()
				try:
					result = df.chat(  # type: ignore
						f"{query} return the result as a dataframe with only relevant columns."
					)
				except Exception:  # noqa: BLE001
					logger.exception("Natural-language search failed")
					st.error(
						"La recherche a échoué. Réessaie avec une autre formulation, "
						"ou réessaie plus tard si le problème persiste."
					)
					st.stop()
			if result is None:
				st.warning("Aucun résultat pour cette question.")
			else:
				st.dataframe(result, use_container_width=True)
		st.caption(
			"Cette recherche lit uniquement une copie en mémoire des données (lecture seule) — "
			"jamais d'écriture en base depuis une requête en langage naturel."
		)

	with tab_charts:
		col1, col2 = st.columns(2)
		with col1:
			fig_price = px.histogram(
				df, x="min_price", nbins=30, title="Distribution des prix minimums"
			)
			st.plotly_chart(fig_price, use_container_width=True)
		with col2:
			top_suppliers = (
				df.groupby("supplier_name")["supplier_service_score"]
				.mean()
				.sort_values(ascending=False)
				.head(10)
				.reset_index()
			)
			fig_suppliers = px.bar(
				top_suppliers,
				x="supplier_service_score",
				y="supplier_name",
				orientation="h",
				title="Top 10 fournisseurs par score de service",
			)
			st.plotly_chart(fig_suppliers, use_container_width=True)

		fig_country = px.box(
			df, x="country_name", y="min_price", title="Distribution des prix par pays fournisseur"
		)
		st.plotly_chart(fig_country, use_container_width=True)
