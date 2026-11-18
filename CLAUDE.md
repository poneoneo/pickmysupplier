# CLAUDE.md — sourcing_intel_cli

Ce fichier donne à Claude Code tout le contexte nécessaire pour travailler sur
ce projet sans repartir de zéro. Lis-le en entier avant toute modification.

## Contexte et objectif du projet

Portfolio personnel pour O'Neal, agent de vente télécom (Vidéotron) en
reconversion vers l'analyse de données. **Ce projet n'est pas destiné à la
commercialisation** — c'est une pièce de portfolio, à garder privée ou
clairement labellisée comme projet éducatif.

**Historique important** : ce projet s'appelait à l'origine
`aba_cli_scrapper` / `Alibaba-CLI-Scraper` et scrapait Alibaba.com. Il a été
renommé en `sourcing_intel_cli` pour retirer toute référence à la marque
Alibaba, après une discussion sur les risques juridiques du scraping (les
CGU d'Alibaba interdisent explicitement la récupération systématique de
contenu — voir précédent *hiQ v. LinkedIn* : le CFAA ne s'applique pas au
scraping de pages publiques, mais la violation de contrat (CGU) reste un
risque réel et a fait perdre ce type d'affaire par le passé). Le projet cible
toujours le même type de site (marketplace B2B), mais :
- **Ne jamais réintroduire "Alibaba" dans un nom de fichier, variable, ou
  commentaire.**
- **Ne jamais aider à transformer ce projet en produit commercial** sans que
  l'utilisateur ait explicitement confirmé avoir vérifié la situation
  juridique.
- Rester conscient que le scraping en lui-même reste une zone grise légale,
  acceptée ici uniquement dans un cadre non-commercial/portfolio.

## Ce que fait le projet

Pipeline de sourcing B2B : scrape une marketplace de produits/fournisseurs,
valide les données, les stocke, puis permet de les explorer via une
**application Streamlit unique** (`app.py`) — recherche en langage naturel +
graphiques. Il n'y a plus de CLI ni de serveur MCP (retirés volontairement
pour réduire l'ambition/complexité — voir section Historique des décisions).

L'app est multi-pages via `st.navigation` : **Accueil** (pitch + bannière de
quota), **Explorer** (sélecteur de jeu de données + recherche en langage
naturel + graphiques), **Scraper** (scraping en direct + jeu de démo —
la clé ScrapingBee personnelle du visiteur est **obligatoire** pour
scraper, pas de clé partagée sur le site : voir Historique des décisions,
2026-09-06), **Aide** (guide d'onboarding : où trouver une clé ScrapingBee
gratuite, comment les données sont organisées, mode d'emploi).
Thème sombre (`.streamlit/config.toml`).

## Stack technique

- **Scraping** : Playwright (`playwright.request` comme client HTTP pur, pas de
  navigateur piloté), via ScrapingBee (API REST, proxy premium sans rendu JS),
  qui interroge l'API de recherche produits du site (JSON) — voir Historique
  des décisions (2026-11-18).
  Syphoon a été retiré (service disparu) puis BrightData (CDP, Scraping
  Browser) a aussi été retiré le 2026-08-20 à la demande de l'utilisateur —
  ScrapingBee est maintenant le seul fournisseur de proxy. Chaque visiteur
  doit fournir sa propre clé gratuite pour scraper (bouton "Scrape live"
  désactivé sans clé) — pas de clé partagée/démo sur le site public, voir
  Historique des décisions (2026-09-06).
- **Parsing HTML** : `selectolax`
- **Modèles/DB** : SQLModel + SQLAlchemy, backend SQLite uniquement
  (`create_db_engine` accepte n'importe quelle URL SQLAlchemy, mais aucune
  interface ne propose autre chose que SQLite — le support MySQL dédié a
  été retiré, voir Historique des décisions)
- **Validation des données** : module maison déterministe (pas de LLM),
  voir section dédiée ci-dessous
- **Interface** : Streamlit (`app.py`) — remplace l'ancien CLI Typer/Click
- **Recherche en langage naturel** : appel direct à l'API Groq
  (`sourcing_intel_cli/nl_search.py`), **pas** de génération/exécution de
  code arbitraire. Historique : utilisait `datahorse` (qui fait exactement
  ça — demande à un LLM d'écrire une fonction pandas et l'`exec()`), retiré
  après tests réels le 2026-08-15 : avec le petit modèle
  `llama-3.1-8b-instant`, le code généré changeait à chaque appel pour la
  même question (parfois cassé, parfois de bonnes colonnes dans le mauvais
  ordre côté graphique). `build_query_spec()` demande à la place une petite
  spec JSON structurée (`{"filters": [...], "sort_by", "ascending",
  "limit", "columns"}` — via le JSON mode de Groq), et `apply_query_spec()`
  l'exécute nous-mêmes avec pandas, de façon déterministe. `datahorse` a
  été retiré des dépendances. Jamais de connexion DB directe depuis une
  requête utilisateur — contrainte de sécurité volontaire, voir plus bas.
  **Important** : le LLM ne voit jamais les vraies valeurs des colonnes
  catégorielles (seulement noms/types) — `build_value_hints()` les injecte
  dans le prompt, sinon un filtre sur `country_name` devine `"China"` alors
  que les données stockent `"chine"` (minuscule, français — voir
  `utils_scrapping.country_name`), et retourne silencieusement zéro ligne.
- **Visualisation** : ECharts, thème sombre — `chart_builder.py` construit
  les dicts d'`option` ECharts (histogramme/barres/boîte à
  moustaches/nuage de points/carte) au lieu de `plotly.express` (retiré).
  `render_echarts_html()` (`chart_builder.py`) rend ces dicts en HTML brut
  (echarts.js + son thème "dark" officiel chargés depuis un CDN, hash
  vérifié via Subresource Integrity), affiché via
  `st.components.v1.html()` — **pas** le package `streamlit-echarts`,
  retiré le 2026-09-06 : son wrapper (épinglé à `0.4.0` pour une
  incompatibilité antérieure, non liée) ne rendait plus aucune série de
  données contre les versions récentes de Streamlit — reproduit avec un
  graphique minimal sans rapport avec le code du projet, donc bug de la
  librairie elle-même, pas du code. La 0.7.0 (dernière version) est pire
  (rien ne s'affiche du tout). Voir Historique des décisions.
- **Logs** : `loguru` ; **affichage terminal legacy** : `rich` (encore
  utilisé dans `proxies_providers.py` pour les messages de progression)

## Structure du projet

```
sourcing_intel_cli_project/
├── app.py                          # Point d'entrée unique (Streamlit)
├── requirements.txt
└── sourcing_intel_cli/
    ├── __init__.py                  # Charge .env (ou st.secrets en repli) : SCRAPINGBEE_API_KEY, GROQ_API_KEY, LOGURU_LEVEL
    ├── nl_search.py                    # build_query_spec() (Groq, JSON mode) + apply_query_spec()
    │                                     (exécution pandas déterministe) + build_value_hints()
    ├── chart_builder.py                  # suggest_chart_type() + build_chart() : sélection de
    │                                       graphique déterministe pour les résultats de recherche NL ;
    │                                       render_echarts_html() : rendu HTML brut (pas de wrapper)
    ├── product_naming.py                  # summarize_product_names() (Groq, repli déterministe
    │                                        truncate_at_word_boundary) : noms de produits raccourcis
    ├── data_coverage.py               # mark_missing_values() / unavailable_columns() : notes vides
    │                                     (0) -> manquantes, champs absents exclus des graphiques et des
    │                                     questions suggérées (voir Historique, 2026-11-18)
    ├── models.py                     # SQLModel: Product, Supplier
    ├── typed_datas.py                 # TypedDict: ProductDict, SupplierDict (contrat scraper -> DB)
    ├── engine_and_database.py          # Connexion DB, add_suppliers_to_db, add_products_to_db
    ├── data_quality.py                  # Agent de qualité déterministe (voir section dédiée)
    ├── demo_data.py                      # generate_demo_data() : dataset synthétique déterministe
    │                                       (seed=42), même forme qu'un vrai scrape, passe par le
    │                                       même pipeline run_quality_checks/add_*_to_db — sert de
    │                                       repli quand le scraping live échoue (site restructuré,
    │                                       plus de crédits proxy, pas de réseau)
    ├── scrape_from_disk.py               # PageParser: HTML brut -> ProductDict/SupplierDict
    ├── html_to_disk.py                    # Extraction JSON depuis le HTML scrapé (json_hunter)
    ├── utils_scrapping.py                  # Parsing de champs spécifiques (prix, certifications, etc.)
    ├── proxies_providers.py                 # ScrapingBeeProxyProvider (scraping)
    ├── proxies_utils.py                      # urls_pusher (utilitaire Playwright)
    └── pays_data.json                         # Table de correspondance code pays -> nom complet
```

**Important** : `app.py` importe `from sourcing_intel_cli.xxx import ...` —
il doit donc rester au même niveau que le dossier `sourcing_intel_cli/`, pas
dedans. Lancer avec `streamlit run app.py` depuis la racine du projet.

## Modèle de données

**Supplier** : `name` (unique), `verification_mode`, `sopi_level` (int),
`country_name`, `years_as_gold_supplier` (int), `supplier_service_score` (float)

**Product** : `name` (unique **par fournisseur**, pas globalement — contrainte
composite `(name, supplier_id)` ; deux fournisseurs différents peuvent
légitimement poster un produit au même nom/titre, chacun à son propre prix —
un unique global aurait silencieusement jeté tous les fournisseurs sauf le
premier à scraper un titre donné, empêchant toute comparaison de prix entre
fournisseurs), `short_name` (nullable — voir
`product_naming.py` ci-dessous), `alibaba_guranteed` (bool — faute
d'orthographe conservée intentionnellement, cohérente entre le modèle et le
code d'insertion, ne pas "corriger" sans mettre à jour partout), `certifications`,
`minimum_to_order`, `ordered_or_sold`, `supplier_id` (FK, non-null en
pratique), `min_price`, `max_price`, `product_score`, `review_count`,
`review_score`, `shipping_time_score`, `is_full_promotion`,
`is_customizable`, `is_instant_order`, `trade_product`

**`short_name`** : les titres scrapés sont souvent de longues chaînes
marketing (`product_naming.summarize_product_names`, appelé dans
`app.py::_validate_and_insert` juste avant l'écriture en base). Résume via
Groq (JSON mode, un seul appel batché pour tous les noms trop longs d'un
scrape) ; si l'appel échoue ou que la réponse n'est pas fiable (manquante,
vide, ou pas réellement plus courte que l'original), repli déterministe
sans réseau sur `truncate_at_word_boundary` (coupe aux limites de mots,
retire les mots de remplissage marketing). Une ligne n'est donc jamais
perdue, seulement raccourcie. Comme `product` existait déjà avec des
lignes réelles avant l'ajout de cette colonne, et que ce projet n'a pas
d'outil de migration, `engine_and_database._ensure_product_short_name_column`
fait un `ALTER TABLE` idempotent au démarrage si la colonne manque.

## Flux de données (bout en bout)

Tout ce que produit un scrape en direct est namespacé sous
`sessions/<session_id>/` (`session_id` généré par `app.py::_get_session_id()`,
stocké dans `st.session_state`) — l'hébergement public reçoit plusieurs
visiteurs en même temps, donc sans cet espacement un visiteur pouvait voir
les données scrapées par un autre ; voir
`docs/superpowers/specs/2026-09-05-session-scoped-data-isolation-design.md`
pour le détail.

1. `proxies_providers.py` scrape des pages HTML brutes → sauvegardées sur
   disque via `html_to_disk.write_to_disk`, dans
   `sessions/<session_id>/scraped_pages/<slug>/` (dossier dérivé de
   `app.py` : `f"sessions/{session_id}/scraped_pages/{slug}"`, `slug` venant
   de `datasets.slugify(keywords)`). Tout `sessions/` est gitignored en
   bloc, donc peu importe les mots-clés recherchés ou le visiteur, aucun
   HTML scrapé ne finit committé par erreur
2. `scrape_from_disk.PageParser` relit ces fichiers HTML, extrait le JSON
   embarqué (`html_to_disk.json_hunter`), et produit des listes de
   `SupplierDict` / `ProductDict`
3. `data_quality.run_quality_checks` valide chaque ligne — **rejette la
   ligne fautive, garde le reste** (politique confirmée avec l'utilisateur,
   ne pas la changer en "tout bloquer" sans lui redemander)
4. `engine_and_database.add_suppliers_to_db` / `add_products_to_db`
   insèrent les lignes propres dans
   `sessions/<session_id>/db/sourcing_intel_<slug>.sqlite`, avec rollback +
   skip sur `IntegrityError` (doublon)
5. `app.py` lit la base en lecture seule (`pandas.read_sql_query`, jamais
   d'écriture depuis cette voie) pour les graphiques fixes et la recherche
   en langage naturel (`nl_search.build_query_spec`/`apply_query_spec`,
   graphique choisi par `chart_builder.build_chart`)

## Agent de qualité des données (`data_quality.py`)

Règles déterministes, pas de jugement LLM :

- **Suppliers** : nom non vide et unique dans le batch ; `sopi_level` int
  non négatif ; `supplier_service_score` numérique non négatif ;
  `years_as_gold_supplier` convertible en int non négatif
- **Products** : nom non vide et unique **par fournisseur** dans le batch (le
  couple `(name, supplied_by)` — deux fournisseurs différents avec le même
  nom de produit sont conservés tous les deux, seul un même fournisseur qui
  répète le même nom est un vrai doublon) ; `supplied_by` doit
  correspondre à un fournisseur déjà validé (garantit que `supplier_id` ne
  sera jamais nul) ; `min_price <= max_price`, tous deux non négatifs ;
  tous les champs booléens strictement `bool` ; tous les champs numériques
  non négatifs

Produit un rapport (`QualityIssue`) affiché sur la page **Scraper** après
chaque scraping (ou chargement du jeu de démo), et écrit sur disque via
`write_quality_report` (`data_quality_report.json`).

## Variables d'environnement (`.env` à la racine, non committé)

```
SCRAPINGBEE_API_KEY=
GROQ_API_KEY=
LOGURU_LEVEL=CRITICAL
```

Sur un hébergement sans `.env` (ex. Streamlit Community Cloud), `SCRAPINGBEE_API_KEY`
et `GROQ_API_KEY` peuvent aussi venir de `st.secrets` — voir le repli dans
`sourcing_intel_cli/__init__.py`.

## Conventions de code à respecter

- **Indentation par tabulations**, pas des espaces (cohérence avec le code
  existant)
- **Docstrings style Sphinx/reST** : `:param x: ...`, `:type x: ...`,
  `:return: ...`, `:rtype: ...` — tous les fichiers existants suivent ce
  format, le garder pour toute nouvelle fonction
- **Type hints** sur les signatures de fonction
- Logging via `loguru.logger`, pas de `print()` sauf dans `app.py` (Streamlit
  a ses propres primitives d'affichage : `st.success`, `st.error`, etc. —
  les utiliser plutôt que `print`/`rprint`)

## Tests et CI

Suite pytest (`tests/`) + `ruff` + workflow GitHub Actions (`.github/workflows/ci.yml`,
déclenché sur push/PR vers `main`). Voir `CONTRIBUTING.md` pour la
convention de commits/branches.

**Toujours `python -m pytest` / `python -m ruff check .`, jamais `pytest`/
`ruff` seuls** — le package n'est pas installé (pas de `pip install -e .`),
donc seul `python -m` ajoute le répertoire courant à `sys.path` pour que
`import sourcing_intel_cli` fonctionne. `pytest` seul échoue avec
`ModuleNotFoundError`.

**Dépendances épinglées en version exacte (`==`), jamais `>=` seul** —
`requirements.txt`/`requirements-dev.txt` (voir Historique des décisions,
2026-11-17). Mettre à jour une dépendance est un choix explicite : changer
le numéro, relancer `python -m pytest`, puis commit.

## Limitations connues (non résolues intentionnellement)

- **Le scraping live et la recherche en langage naturel ont été validés
  avec de vrais appels** (voir historique des décisions) — mais le reste
  (rendu des graphiques fixes avec de gros volumes de données réelles,
  etc.) n'a toujours pas été testé en conditions réelles au-delà de ce qui
  est documenté ici. **Considère tout le reste comme non validé jusqu'à
  preuve du contraire.**
- **Graphiques ECharts qui ne s'affichaient plus, résolu le 2026-09-06** :
  signalé par l'utilisateur en conditions réelles (pas juste le bac à
  sable de test — vérifié à l'identique dans les deux). Cause confirmée :
  le package `streamlit-echarts` (épinglé à `0.4.0`) ne rendait plus
  aucune série de données contre le Streamlit installé (`1.61.1`) —
  reproduit avec un graphique minimal hardcodé, sans rapport avec le code
  du projet (axes affichés, séries jamais dessinées), donc bug de la
  librairie/son bundle ECharts embarqué, pas du code de l'app. Deux pistes
  écartées avant la solution retenue : `key=` explicite sur chaque
  `st_echarts` (aucun effet), mise à jour vers `streamlit-echarts==0.7.0`
  (pire — plus rien ne s'affiche du tout, confirme la note déjà présente
  dans `requirements.txt` sur l'API "components v2"/`asset_dir` manquante).
  Solution : `chart_builder.render_echarts_html()` contourne le wrapper
  entièrement (HTML brut + echarts.js officiel + son thème "dark" officiel,
  chargés depuis un CDN avec hash Subresource Integrity), affiché via
  `st.components.v1.html()` — dépendance `streamlit-echarts` retirée de
  `requirements.txt`.

## Historique des décisions (pour éviter de revenir en arrière par erreur)

- Le projet avait une couche CLI (Typer/Click, `commands.py`) et un serveur
  MCP (`mcp_server.py`, avec orchestrateur et diagnostic de sélecteurs
  CSS) — **retirés délibérément** à la demande de l'utilisateur pour
  réduire l'ambition et centraliser sur une seule interface Streamlit.
  Ne pas les recréer sans demande explicite.
- `db_credentials.json` (pour MySQL) était protégé en écriture (`chmod 600`)
  dans l'ancienne version CLI — cette protection n'existe plus car MySQL
  n'est plus exposé ; à réintroduire si MySQL revient dans l'interface.
- Les chemins d'erreur `return typer.Exit(...)` de `proxies_providers.py`
  (reliquat de l'ancien CLI Typer/Click) ont été remplacés par de vraies
  exceptions (`RuntimeError`) ; `typer`/`click` ne sont plus importés nulle
  part dans le projet.
- Le support MySQL dédié (`pymysql`, gestion spécifique de
  `MySQLdbOperationalError` dans `engine_and_database.save_all_changes`) a
  été retiré — c'était du code mort depuis le retrait de l'ancien
  `commands.py`/`db-init mysql`. `create_db_engine` reste générique
  (accepte toute URL SQLAlchemy) mais plus rien ne construit d'URL MySQL
  côté interface.
- **Modèle Groq changé le 2026-08-17** : `llama-3.1-8b-instant` a été
  décommissionné côté Groq (erreur 404 `model_not_found`) ; `nl_search.py`
  et `product_naming.py` utilisent maintenant `openai/gpt-oss-20b`
  (`GROQ_MODEL`, remplacement suggéré par Groq pour ce type de charge
  légère/JSON mode). Revérifié avec un vrai appel Groq le 2026-08-24 —
  `build_query_spec()`/`apply_query_spec()` fonctionnent toujours
  correctement avec ce modèle.
- **BrightData retiré le 2026-08-20** à la demande de l'utilisateur —
  `BrightDataProxyProvider`, `_with_country_targeting`, `goto_task`
  (`proxies_utils.py`, devenu mort avec le retrait) et `BRIGHT_DATA_API_KEY`
  ont tous été supprimés. ScrapingBee (clé BYO gratuite) est maintenant le
  seul fournisseur de proxy — plus de sélecteur dans la page Scraper.
- **Hébergement public déployé le 2026-08-20** sur Streamlit Community
  Cloud : https://pickmysupplier.streamlit.app/ (repli `st.secrets` déjà en
  place, voir Variables d'environnement). L'app se met en veille après une
  période d'inactivité (comportement standard du tier gratuit) — un visiteur
  doit cliquer « Yes, get this app back up! » pour la réveiller, redémarrage
  vérifié en conditions réelles le 2026-08-25.
- **Clé ScrapingBee rendue obligatoire le 2026-09-06** — l'utilisateur ne
  veut plus qu'une clé "démo"/partagée existe comme chemin normal côté UI
  (elle avait fini par exister de fait sur le site public quand sa propre
  clé personnelle a été utilisée pour des tests). Page Scraper : le champ
  clé passe en étape 1 (avant les mots-clés), le bouton "Scrape live" est
  désactivé tant qu'aucune clé n'est saisie (`disabled=not keywords or not
  user_scrapingbee_key` dans `app.py::page_scraper`), et les messages
  d'avertissement "clé démo" ont été retirés (un seul message "ta clé ne
  fonctionne pas" reste, `sb_quota_exhausted_own_key` a disparu du
  session_state). Le fallback technique `SCRAPINGBEE_API_KEY`/`.env` dans
  `_resolve_scrapingbee_key` (`proxies_providers.py`) n'a pas été retiré du
  code (filet de sécurité pour les tests locaux de l'auteur), mais ne doit
  **jamais** être configuré dans `st.secrets` sur l'hébergement public —
  sinon on recrée exactement le problème qu'on vient de corriger.
- **Dépendances épinglées en version exacte le 2026-11-17** — après une
  pause de plusieurs semaines sans toucher au projet, le redémarrage du
  site sur Streamlit Cloud a réinstallé les dépendances depuis
  `requirements.txt` et tiré `selectolax==1.0.0` (sorti le 2026-10-03,
  retire complètement `selectolax.parser`) : `ImportError` au démarrage
  (`app.py` → `demo_data.py` → `utils_scrapping.py`). Fix en 2 temps (PR
  #31 puis ce commit) : migration du code vers `selectolax.lexbor`
  (`LexborHTMLParser`/`LexborNode`, API vérifiée équivalente — `css`,
  `css_first`, `attrs`/`attributes`, `text()`), puis — à la demande
  explicite de l'utilisateur, qui veut "un projet fixe qui ne mettra à
  jour ses deps que par nécessité du projet" — remplacement de **toutes**
  les bornes `>=` de `requirements.txt`/`requirements-dev.txt` par des
  épinglages exacts (`==`) sur les versions alors installées et testées
  (`pip freeze`, 198 tests + `ruff` verts). Révèle au passage que
  `pandas` (3.0.5) et `numpy` (2.5.2) avaient déjà silencieusement sauté
  une version majeure sans que personne ne le remarque — aucun crash
  visible, mais exactement le même risque latent que `selectolax`.
  Dependabot explicitement écarté (l'utilisateur ne veut pas de PR de mise
  à jour automatique) — une mise à jour de dépendance se fait maintenant
  à la main, numéro par numéro, dans `requirements.txt`.
- **Hébergement déplacé sur un VPS le 2026-11-18** (PR #34 + PR suivante) —
  l'utilisateur voulait un site **jamais en veille ET sur son propre
  domaine**, deux choses impossibles sur Streamlit Community Cloud gratuit.
  Hetzner écarté (tout en rupture de stock en novembre 2026, ~21 $/mois aux
  USA) au profit d'un **OVHcloud VPS-1** (2 vCore, 4 Go, Beauharnois QC,
  sans engagement, ~7,30 $ CAD/mois HT), IP `158.69.193.136`, domaine
  **pickmysupplier.com** (OVH, DNSSEC). Stack : `Dockerfile` + `deploy/`
  (Caddy pour le HTTPS automatique et la redirection `www` → domaine nu) ;
  la GitHub Action `deploy.yml` redéploie après chaque CI verte sur `main`,
  via une clé SSH restreinte côté serveur (`command=` dans
  `authorized_keys`) au seul `deploy/deploy.sh`. Secrets serveur dans
  `/opt/pickmysupplier/deploy/.env` (`DOMAIN`, `GROQ_API_KEY`,
  `LOGURU_LEVEL` — **jamais** `SCRAPINGBEE_API_KEY`, même règle que
  2026-09-06). Piège trouvé en conditions réelles : l'image Ubuntu d'OVH
  livre un `50-cloud-init.conf` avec `PasswordAuthentication yes`, et sshd
  garde la *première* valeur lue — le durcissement doit donc être en
  `00-…conf`. L'ancienne adresse `pickmysupplier.streamlit.app` est
  **gardée volontairement** (elle est sur le CV de l'utilisateur) mais
  n'affiche plus que « site has moved » + un bouton vers le nouveau
  domaine : `sourcing_intel_cli/site_move.py` valide `MOVED_TO_URL`, un
  réglage présent **uniquement** dans les secrets Streamlit Cloud (jamais
  sur le VPS). Streamlit Cloud n'offre pas de redirection serveur, et la
  tentative JS est bloquée par le sandbox des iframes Streamlit — le bouton
  est le chemin fiable, et cette adresse continue de se mettre en veille.

- **Scraping live réparé le 2026-11-18** (PR #39 + #40) — les visiteurs
  vidaient leurs crédits ScrapingBee sans rien obtenir. Mesuré avec de
  vrais appels : (1) en proxy premium + JS, la page de résultats HTML
  renvoyait un captcha 3 fois sur 3, facturé 25 crédits comme une vraie
  page (HTTP 200) ; (2) ScrapingBee répond 401 (pas 429) quand le quota
  mensuel est épuisé, et l'app disait alors « clé invalide » ; (3) la page
  HTML n'embarque plus le JSON `window.__page__data_sse*._offer_list` —
  les résultats n'y sont plus que dans les cartes `.fy26-product-card`,
  **sans** les scores produit/livraison/service ni les noms de
  certifications. Seul le proxy stealth (75 crédits/page) passait le
  captcha. Solution retenue, **avec l'accord explicite de l'utilisateur**
  (il a accepté le risque CGU supplémentaire d'appeler une API interne non
  documentée, au-delà du scraping de pages publiques) : le scraper
  interroge l'API de recherche produits du site
  (`proxies_utils.SEARCH_API_URL`, JSON, 40 offres/page) — tous les champs
  y sont (`supplierServiceScore` renommé `supplierService`), pour
  **10 crédits/page** (premium sans JS, `country_code` + `currency=USD`).
  Le proxy de base à 1 crédit marche aussi mais la devise suit le nœud de
  sortie même avec `currency=USD` (2 fois sur 3 en USD, sinon GBP) —
  écarté. Garde-fou : `is_usd_price` rejette toute offre hors USD (le
  symbole est retiré au parsing, elle serait sinon stockée comme des
  dollars). Seul champ perdu : le badge « vérifié » par offre (absent de
  l'API) → `verification_mode = "unknown"`, jamais deviné. Les pages HTML
  restent lisibles (`card_to_offer`, repli sur les cartes) si l'API
  disparaît. Arrêt dès le premier captcha (`TargetSiteBlockedError`) et
  `ScrapingBeeKeyError.reason` (`quota`/`invalid`) gardés.

- **Couverture des données le 2026-11-18** (même PR #40) — un scrape
  live ne remplit pas toutes les colonnes : pas de statut « vérifié »
  (`"unknown"`), les 5 booléens jamais fournis (False), et des notes
  laissées vides par le site (stockées 0.0). Lues telles quelles, elles
  faussaient l'analyse (une note vide comptée 0/5 tire toutes les moyennes
  vers le bas ; un graphique « Trade Assurance » à 0 % partout).
  `data_coverage.py` les transforme **à la lecture** (pas de migration de
  schéma) : notes à 0 -> NaN, `"unknown"` -> manquant ; colonnes sans
  aucune donnée -> exclues des graphiques fixes (remplacées ou signalées)
  et des questions suggérées (qui sont aussi remplies avec les vraies
  valeurs du jeu : pays, certification) ; avertissement si une question en
  langage naturel porte sur un champ absent (`apply_query_spec` ignore
  sinon le filtre en silence et renverrait tout, comme si tout était
  vérifié) ; note visible sur la page Explore (« non disponible », « en
  partie vide : X % »). Le jeu de démo, complet, n'est pas concerné.
  Trouvé au passage : 13 offres réelles sur 80 (produits sans avis, surtout
  de nouveaux fournisseurs) n'ont pas de clé `reviewCount` et étaient
  **jetées en silence** par un KeyError — biais vers les produits déjà
  notés. Les scores sont maintenant optionnels dans `_produtcs_appender`
  (68 produits retenus au lieu de 57 sur les mêmes pages).

## Prochaines étapes possibles (non commencées)

- Commitizen (version bump + changelog automatique) et packaging pipx —
  tous deux explicitement reportés par l'utilisateur, voir
  `project_deferred_packaging_versioning` en mémoire

Export CSV, retrait de BrightData et hébergement public (annoncés dans le
README le 2026-08-20) sont maintenant faits — voir Historique des
décisions.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
