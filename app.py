"""Sourcing Intel — multi-page Streamlit app: scrape, validate, browse, and
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
		if st.session_state.get("sb_quota_exhausted_own_key"):
			st.warning(
				"⚠️ Ta clé ScrapingBee ne fonctionne pas (quota de crédits épuisé, "
				"ou clé invalide/expirée) — vérifie ton compte ScrapingBee ou réessaie plus tard."
			)
		else:
			st.warning(
				"⚠️ La clé ScrapingBee de démo ne fonctionne pas pour l'instant "
				"(quota épuisé ou clé expirée) — récupère la tienne gratuitement, "
				"voir la page **Aide**."
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

	st.download_button(
		"⬇️ Télécharger ce jeu de données (CSV)",
		data=df.to_csv(index=False).encode("utf-8"),
		file_name=f"{selected_label}.csv",
		mime="text/csv",
		help="Le jeu de données brut affiché ci-dessous — produits joints à leur fournisseur.",
	)

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
					- `minimum_to_order` — quantité minimale de commande (MOQ)
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

		st.markdown(
			"**Exemples de questions à poser** — le graphique entre parenthèses est celui "
			"que « Auto » choisit réellement pour cette formulation (vérifié, pas juste indicatif) :"
		)
		st.markdown(
			"""
			- *Quels sont les 5 fournisseurs avec le meilleur supplier_service_score ?* (Barres)
			- *Quelle est la distribution des prix minimums ?* (Histogramme)
			- *Quelle est la dispersion du product_score par pays fournisseur ?* (Boîte à moustaches)
			- *Y a-t-il une corrélation entre le product_score et le min_price ?* (Nuage de points)
			- *Compare le prix moyen des produits par pays fournisseur.* (Barres)
			- *Quelle est la distribution du MOQ (quantité minimale de commande) ?* (Histogramme)
			- *Quels pays sont représentés parmi les fournisseurs ?* (Carte du monde)
			- *Liste les fournisseurs en Chine avec au moins 5 ans d'ancienneté Gold Supplier, triés par prix minimum.* (Tableau — choisis "Tableau seulement" dans le menu, "Auto" ne détecte pas ce cas et affichera des barres par défaut)
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
			"Carte du monde": "map",
		}
		chart_type_choice = st.selectbox("Type de graphique", list(chart_type_labels.keys()))

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
			"Chercher", disabled=(not query) or st.session_state["nl_search_running"]
		):
			st.session_state["nl_search_running"] = True
			st.rerun()

		if st.session_state["nl_search_running"]:
			with st.spinner("Recherche en cours..."):
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
						"La recherche a échoué. Réessaie avec une autre formulation, "
						"ou réessaie plus tard si le problème persiste."
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
					"Je n'ai pas compris cette question — essaie de mentionner un "
					"critère précis (prix, score, pays, fournisseur...)."
				)
			elif result.empty:
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
					# The map's GeoJSON is registered separately from the
					# option dict — st_echarts(map=...) is how ECharts
					# learns what "world" (referenced in
					# option["series"][0]["map"]) actually resolves to.
					map_arg = Map("world", _load_world_geojson()) if resolved_type == "map" else None
					st_echarts(options=option, theme="dark", height="500px", map=map_arg)
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
				"Top 10 fournisseurs par score de service",
				horizontal=True,
			)
			st_echarts(options=option_suppliers, theme="dark", height="500px")

		option_country = build_box_option(
			df, "country_name", "min_price", "Distribution des prix par pays fournisseur"
		)
		st_echarts(options=option_country, theme="dark", height="500px")


def page_scraper() -> None:
	"""Live scraping controls, demo dataset loader, and the ScrapingBee BYO-key field."""
	st.title("Scraper")

	if st.session_state.get("sb_quota_exhausted"):
		if st.session_state.get("sb_quota_exhausted_own_key"):
			st.warning(
				"⚠️ Ta clé ScrapingBee ne fonctionne pas (quota de crédits épuisé, "
				"ou clé invalide/expirée) — vérifie ton compte ScrapingBee ou réessaie plus tard."
			)
		else:
			st.warning(
				"⚠️ La clé ScrapingBee de démo ne fonctionne pas pour l'instant "
				"(quota épuisé ou clé expirée) — récupère la tienne gratuitement "
				"(voir la page **Aide**) ou saisis-la ci-dessous."
			)

	keywords = st.text_input("Mots-clés", placeholder="ex: wireless earbuds")
	page_results = st.number_input("Nombre de pages", min_value=1, max_value=50, value=5)

	user_scrapingbee_key = st.text_input(
		"Ta clé ScrapingBee (facultatif)",
		type="password",
		help="Laisse vide pour utiliser la clé de démo du site. Voir la page "
		"Aide pour savoir où trouver la tienne, gratuitement.",
		key="user_scrapingbee_key",
	)

	if st.button("Scraper en direct", type="primary", disabled=not keywords):
		slug = slugify(keywords)
		save_in_folder = f"scraped_pages/{slug}"

		with st.spinner("Scraping en cours (peut prendre plusieurs minutes)..."):
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
						"Ta clé ScrapingBee ne fonctionne pas (quota de crédits épuisé, ou "
						"clé invalide/expirée). Vérifie ton compte ScrapingBee ou réessaie plus tard."
					)
				else:
					st.error(
						"La clé ScrapingBee de démo ne fonctionne pas (quota épuisé ou "
						"clé expirée). Récupère la tienne gratuitement (voir la page Aide) "
						"ou saisis-la ci-dessus."
					)
				st.stop()
			except Exception:  # noqa: BLE001
				logger.exception("Scraping failed")
				st.error("Le scraping a échoué. Voir logs/app.log pour le détail.")
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
