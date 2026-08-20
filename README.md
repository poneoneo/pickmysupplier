# Sourcing Intel

<p align="center"><b>Scrape une marketplace B2B, valide les données, et discute-les en langage naturel.</b></p>

<div align="center">

[![CI](https://github.com/poneoneo/pickmysupplier/actions/workflows/ci.yml/badge.svg)](https://github.com/poneoneo/pickmysupplier/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/poneoneo/pickmysupplier/branch/main/graph/badge.svg)](https://codecov.io/gh/poneoneo/pickmysupplier)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![Streamlit](https://img.shields.io/badge/streamlit-1.36%2B-FF4B4B?logo=streamlit&logoColor=white)

</div>

> **Projet portfolio personnel, non destiné à la commercialisation.** Réalisé
> par [O'Neal](https://github.com/poneoneo) en reconversion vers l'analyse
> de données. Le code est sous licence MIT (voir [License](#license)), mais
> l'intention reste éducative — pas un produit commercial. Voir
> [`CLAUDE.md`](CLAUDE.md) pour tout l'historique de décisions du projet.

---

## Table des matières

- [À propos](#à-propos)
- [Fonctionnalités](#fonctionnalités)
- [Quelles données sont récupérées ?](#quelles-données-sont-récupérées-)
- [Pipeline de données](#pipeline-de-données)
- [Prérequis](#prérequis)
- [Installation](#installation)
- [Variables d'environnement](#variables-denvironnement)
- [Utiliser l'application](#utiliser-lapplication)
  - [🏠 Accueil](#-accueil)
  - [🔍 Explorer](#-explorer)
  - [🕷️ Scraper](#️-scraper)
  - [❓ Aide](#-aide)
- [Agent de qualité des données](#agent-de-qualité-des-données)
- [Développement](#développement)
- [État du projet](#état-du-projet)
- [Contribuer](#contribuer)
- [License](#license)

## À propos

**Sourcing Intel** est une application Streamlit qui scrape une marketplace
B2B (produits + fournisseurs), valide chaque ligne avec un agent de qualité
déterministe, la stocke en base SQLite, puis te laisse l'explorer par
**recherche en langage naturel** et par **graphiques** — comme un·e
acheteur·se qui compare des centaines de fournisseurs sans ouvrir un seul
onglet en plus.

Ancien nom du projet : `aba_cli_scrapper` / `Alibaba-CLI-Scraper` — renommé
pour retirer toute référence à la marque Alibaba après une réflexion sur les
risques juridiques du scraping de marketplace (voir
[`CLAUDE.md`](CLAUDE.md#contexte-et-objectif-du-projet) pour le détail). Le
projet a aussi perdu sa couche CLI (Typer/Click) et son serveur MCP en cours
de route, au profit d'une seule interface Streamlit — volontairement plus
simple à maintenir qu'un outil multi-interfaces.

## Fonctionnalités

- **2 fournisseurs de proxy interchangeables** pour le scraping : BrightData
  (Scraping Browser, CDP) et ScrapingBee (API REST, rendu JS côté serveur) —
  avec repli automatique et message clair si le quota/la clé pose problème.
- **Recherche en langage naturel sans exécution de code arbitraire** : la
  question est transformée par un LLM (Groq, JSON mode) en une petite spec
  structurée (`filtres`, `tri`, `colonnes`), exécutée nous-mêmes avec pandas
  — jamais de code généré par une IA exécuté à l'aveugle sur les données.
- **Graphiques ECharts** : histogramme, barres, boîte à moustaches, nuage de
  points, carte du monde — sélection automatique du type de graphique adapté
  à la question posée (ou choix manuel).
- **Agent de qualité des données déterministe** (`data_quality.py`) : aucune
  décision prise par un LLM — une ligne fautive est rejetée, le reste de la
  base reste propre. Rapport détaillé affiché après chaque scraping.
- **Résumé automatique des noms de produits** trop longs (titres marketing)
  via Groq, avec repli déterministe sans réseau si l'appel échoue.
- **Jeu de données de démo** intégré (déterministe, seed fixe) qui traverse
  exactement le même pipeline qu'un vrai scraping — pour explorer l'app sans
  dépendre de la disponibilité du site cible.
- **Une base de données par recherche** : deux recherches différentes ne
  mélangent jamais leurs résultats, sélecteur de jeu de données dans
  l'interface.
- **Clé ScrapingBee "bring your own key"** : utilise la clé de démo du site
  par défaut, ou la tienne — avec un guide pas-à-pas dans la page Aide pour
  en récupérer une gratuitement.

## Quelles données sont récupérées ?

Champs liés aux **fournisseurs** (`Supplier`) :

| Champ | Type | Description |
|---|---|---|
| `name` | `str` | Nom du fournisseur (unique) |
| `verification_mode` | `str` | Mode de vérification (ex. `verified`/`unverified`) |
| `sopi_level` | `int` | Niveau de performance |
| `country_name` | `str` | Pays du fournisseur |
| `years_as_gold_supplier` | `int` | Ancienneté Gold Supplier |
| `supplier_service_score` | `float` | Note de service |

Champs liés aux **produits** (`Product`) :

| Champ | Type | Description |
|---|---|---|
| `name` | `str` | Nom complet du produit (unique **par fournisseur**) |
| `short_name` | `str \| None` | Version raccourcie du nom, générée par IA |
| `alibaba_guranteed` | `bool` | Protégé par Trade Assurance *(nom conservé volontairement, voir `CLAUDE.md`)* |
| `certifications` | `str` | Certifications listées |
| `minimum_to_order` | `int` | Quantité minimale de commande (MOQ) |
| `ordered_or_sold` | `int` | Nombre de commandes/ventes |
| `supplier_id` | `int` | Clé étrangère vers le fournisseur |
| `min_price` / `max_price` | `float` | Fourchette de prix |
| `product_score` | `float` | Note du produit |
| `review_count` / `review_score` | `float` | Nombre d'avis et note moyenne |
| `shipping_time_score` | `float` | Note de délai de livraison |
| `is_full_promotion` | `bool` | En promotion |
| `is_customizable` | `bool` | Personnalisable |
| `is_instant_order` | `bool` | Commande instantanée disponible |
| `trade_product` | `bool` | Protégé par Trade Assurance |

Modèles complets : [`sourcing_intel_cli/models.py`](sourcing_intel_cli/models.py).

## Pipeline de données

```
1. proxies_providers.py   → scrape des pages HTML brutes (BrightData/ScrapingBee)
2. html_to_disk.py        → sauvegarde sur disque (scraped_pages/<mots-clés>/)
3. scrape_from_disk.py    → relit le HTML, extrait le JSON embarqué → SupplierDict/ProductDict
4. data_quality.py        → valide chaque ligne (rejette la ligne fautive, garde le reste)
5. engine_and_database.py → insère les lignes propres (rollback + skip sur doublon)
6. app.py                 → lecture seule pour les graphiques et la recherche NL
```

Détail complet du flux et des décisions d'architecture : voir
[`CLAUDE.md`](CLAUDE.md#flux-de-données-bout-en-bout).

## Prérequis

- Python 3.12 ou supérieur
- Une clé API [Groq](https://console.groq.com) (gratuite) pour la recherche
  en langage naturel et le résumé des noms de produits
- Une clé API [ScrapingBee](https://www.scrapingbee.com) (plan gratuit
  disponible — voir la page **Aide** de l'app pour le guide pas-à-pas) ou
  [BrightData](https://get.brightdata.com) pour le scraping

## Installation

```bash
git clone https://github.com/poneoneo/pickmysupplier.git
cd pickmysupplier
pip install -r requirements.txt
streamlit run app.py
```

L'application n'est pas distribuée en package (pas de PyPI/pipx) — c'est un
projet portfolio à faire tourner en local, pas un outil à installer
globalement.

## Variables d'environnement

Fichier `.env` à la racine, non committé (voir `.gitignore`) :

```
BRIGHT_DATA_API_KEY=
SCRAPINGBEE_API_KEY=
GROQ_API_KEY=
LOGURU_LEVEL=CRITICAL
```

## Utiliser l'application

L'app est multi-pages via `st.navigation` — quatre pages accessibles depuis
la barre latérale.

### 🏠 Accueil

Pitch du projet, bannière d'alerte si le quota de la clé ScrapingBee (démo
ou personnelle) est épuisé, liens rapides vers les trois autres pages.

### 🔍 Explorer

Sélectionne un jeu de données (une base par recherche passée, y compris la
démo), puis deux onglets :

- **Recherche en langage naturel** — pose une question en français
  (ex. *"quels sont les 5 fournisseurs les mieux notés en Chine ?"*).
  La question est transformée en filtre/tri structuré exécuté par pandas,
  jamais en code généré par une IA. Choix du type de graphique manuel ou
  automatique (histogramme, barres, boîte à moustaches, nuage de points,
  carte du monde, ou tableau seul).
- **Graphiques** — distribution des prix, top 10 fournisseurs par score de
  service, dispersion des prix par pays fournisseur.

### 🕷️ Scraper

Lance un scraping en direct (mots-clés + fournisseur de proxy + nombre de
pages), avec un champ optionnel pour utiliser ta propre clé ScrapingBee.
Un bouton **"Charger le jeu de données de démo"** permet d'explorer l'app
sans dépendre de la disponibilité du site cible (structure susceptible de
changer). Chaque scraping (ou chargement démo) passe par le même pipeline de
validation qualité, avec un rapport affiché juste après.

### ❓ Aide

Guide d'onboarding : comment récupérer une clé ScrapingBee gratuite pas à
pas, comment les données sont organisées (une base par recherche), et un
mode d'emploi condensé (scraping live vs démo, poser une question, lire les
graphiques).

## Agent de qualité des données

Règles **déterministes**, aucun jugement LLM (`sourcing_intel_cli/data_quality.py`) :

- **Fournisseurs** : nom non vide et unique dans le lot ; `sopi_level` entier
  non négatif ; `supplier_service_score` numérique non négatif ;
  `years_as_gold_supplier` convertible en entier non négatif.
- **Produits** : nom non vide et unique **par fournisseur** ; `supplier_id`
  doit correspondre à un fournisseur déjà validé ; `min_price <= max_price`,
  tous deux non négatifs ; tous les champs booléens strictement `bool` ; tous
  les champs numériques non négatifs.

Une ligne fautive est rejetée, le reste du lot est conservé — politique
volontaire, voir [`CLAUDE.md`](CLAUDE.md#flux-de-données-bout-en-bout).

## Développement

```bash
pip install -r requirements-dev.txt
python -m pytest --cov=sourcing_intel_cli   # tests + couverture
python -m ruff check .                       # lint
```

**Toujours `python -m pytest` / `python -m ruff check .`**, jamais `pytest`/
`ruff` seuls — le package n'est pas installé (pas de `pip install -e .`),
donc seul `python -m` ajoute le répertoire courant à `sys.path`.

La CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) lance lint +
tests + couverture sur chaque push/PR vers `main`, et remonte la couverture
vers [Codecov](https://codecov.io/gh/poneoneo/pickmysupplier) (badge en haut
de ce README).

## État du projet

- **Pas de versionning formel pour l'instant** (pas de tags/releases, pas de
  changelog automatique) — Commitizen et un packaging pipx ont été
  envisagés puis explicitement reportés, le projet reste pour l'instant
  suivi uniquement via l'historique Git et les Pull Requests.
- Le scraping live et la recherche en langage naturel ont été validés avec
  de vrais appels ; le reste (rendu des graphiques avec de gros volumes
  réels, etc.) n'a pas encore été testé au-delà de ce qui est documenté dans
  [`CLAUDE.md`](CLAUDE.md#limitations-connues-non-résolues-intentionnellement).

## Contribuer

Voir [`CONTRIBUTING.md`](CONTRIBUTING.md) pour la convention de commits
(Gitmoji) et de branches utilisée sur ce projet — elle s'applique à tous les
commits, y compris ceux de l'auteur principal.

## License

Ce projet est sous licence [MIT](LICENSE).
