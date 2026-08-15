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

## Stack technique

- **Scraping** : Playwright (navigateur headless ou client HTTP `playwright.request`),
  proxies rotatifs via BrightData (CDP, nécessite une clé Scraping Browser active) ou
  ScrapingBee (API REST, rendu JS côté serveur) — deux providers interchangeables.
  Syphoon a été retiré : le service n'existe plus, remplacé par ScrapingBee.
- **Parsing HTML** : `selectolax`
- **Modèles/DB** : SQLModel + SQLAlchemy, backend SQLite (MySQL supporté par
  `engine_and_database.py` mais plus exposé nulle part côté interface —
  code mort à surveiller si on le réactive un jour)
- **Validation des données** : module maison déterministe (pas de LLM),
  voir section dédiée ci-dessous
- **Interface** : Streamlit (`app.py`) — remplace l'ancien CLI Typer/Click
- **Recherche en langage naturel** : `datahorse`, dont l'import enregistre
  `.chat()` comme accessor pandas — s'utilise directement en `df.chat(...)`,
  jamais via `datahorse.read(df)` (cette fonction attend un chemin de
  fichier CSV/Excel, pas un DataFrame — retourne `None` silencieusement si
  on lui passe autre chose). Jamais de connexion DB directe depuis une
  requête utilisateur — contrainte de sécurité volontaire, voir plus bas.
  **Important** : `datahorse` embarque en dur une clé Groq publique et le
  modèle `llama3-8b-8192`, tous deux morts (clé révoquée, modèle
  décommissionné par Groq mi-2025). `sourcing_intel_cli/nl_search.py`
  patche `datahorse.core.client`/`datahorse.core.model` avec notre propre
  `GROQ_API_KEY` et `llama-3.1-8b-instant` — appeler
  `configure_datahorse()` avant tout `df.chat(...)`.
- **Visualisation** : Plotly (`plotly.express`)
- **Logs** : `loguru` ; **affichage terminal legacy** : `rich` (encore
  utilisé dans `proxies_providers.py` pour les messages de progression)

## Structure du projet

```
sourcing_intel_cli_project/
├── app.py                          # Point d'entrée unique (Streamlit)
├── requirements.txt
└── sourcing_intel_cli/
    ├── __init__.py                  # Charge .env : BRIGHT_DATA_API_KEY, SCRAPINGBEE_API_KEY, GROQ_API_KEY, LOGURU_LEVEL
    ├── nl_search.py                    # configure_datahorse() : patche la clé/modèle Groq morts de datahorse
    ├── models.py                     # SQLModel: Product, Supplier
    ├── typed_datas.py                 # TypedDict: ProductDict, SupplierDict (contrat scraper -> DB)
    ├── engine_and_database.py          # Connexion DB, add_suppliers_to_db, add_products_to_db
    ├── data_quality.py                  # Agent de qualité déterministe (voir section dédiée)
    ├── scrape_from_disk.py               # PageParser: HTML brut -> ProductDict/SupplierDict
    ├── html_to_disk.py                    # Extraction JSON depuis le HTML scrapé (json_hunter)
    ├── utils_scrapping.py                  # Parsing de champs spécifiques (prix, certifications, etc.)
    ├── proxies_providers.py                 # BrightDataProxyProvider, ScrapingBeeProxyProvider (scraping)
    ├── proxies_utils.py                      # urls_pusher, goto_task (utilitaires Playwright)
    └── pays_data.json                         # Table de correspondance code pays -> nom complet
```

**Important** : `app.py` importe `from sourcing_intel_cli.xxx import ...` —
il doit donc rester au même niveau que le dossier `sourcing_intel_cli/`, pas
dedans. Lancer avec `streamlit run app.py` depuis la racine du projet.

## Modèle de données

**Supplier** : `name` (unique), `verification_mode`, `sopi_level` (int),
`country_name`, `years_as_gold_supplier` (int), `supplier_service_score` (float)

**Product** : `name` (unique), `alibaba_guranteed` (bool — faute
d'orthographe conservée intentionnellement, cohérente entre le modèle et le
code d'insertion, ne pas "corriger" sans mettre à jour partout), `certifications`,
`minimum_to_order`, `ordered_or_sold`, `supplier_id` (FK, non-null en
pratique), `min_price`, `max_price`, `product_score`, `review_count`,
`review_score`, `shipping_time_score`, `is_full_promotion`,
`is_customizable`, `is_instant_order`, `trade_product`

## Flux de données (bout en bout)

1. `proxies_providers.py` scrape des pages HTML brutes → sauvegardées sur
   disque via `html_to_disk.write_to_disk`
2. `scrape_from_disk.PageParser` relit ces fichiers HTML, extrait le JSON
   embarqué (`html_to_disk.json_hunter`), et produit des listes de
   `SupplierDict` / `ProductDict`
3. `data_quality.run_quality_checks` valide chaque ligne — **rejette la
   ligne fautive, garde le reste** (politique confirmée avec l'utilisateur,
   ne pas la changer en "tout bloquer" sans lui redemander)
4. `engine_and_database.add_suppliers_to_db` / `add_products_to_db` insèrent
   les lignes propres, avec rollback + skip sur `IntegrityError` (doublon)
5. `app.py` lit la base en lecture seule (`pandas.read_sql_query`, jamais
   d'écriture depuis cette voie) pour les graphiques et la recherche
   en langage naturel via `datahorse`

## Agent de qualité des données (`data_quality.py`)

Règles déterministes, pas de jugement LLM :

- **Suppliers** : nom non vide et unique dans le batch ; `sopi_level` int
  non négatif ; `supplier_service_score` numérique non négatif ;
  `years_as_gold_supplier` convertible en int non négatif
- **Products** : nom non vide et unique dans le batch ; `supplied_by` doit
  correspondre à un fournisseur déjà validé (garantit que `supplier_id` ne
  sera jamais nul) ; `min_price <= max_price`, tous deux non négatifs ;
  tous les champs booléens strictement `bool` ; tous les champs numériques
  non négatifs

Produit un rapport (`QualityIssue`) affiché dans la sidebar Streamlit après
chaque scraping, et écrit sur disque via `write_quality_report`
(`data_quality_report.json`).

## Variables d'environnement (`.env` à la racine, non committé)

```
BRIGHT_DATA_API_KEY=
SCRAPINGBEE_API_KEY=
GROQ_API_KEY=
LOGURU_LEVEL=CRITICAL
```

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

## Limitations connues (non résolues intentionnellement)

- **Rien n'a été testé en conditions réelles** (scraping, `datahorse`,
  rendu des graphiques avec vraies données) — l'environnement de
  développement précédent n'avait pas d'accès réseau vers Alibaba/PyPI de
  façon fiable. **Considère tout comme non validé jusqu'à preuve du
  contraire.**
- Dans `proxies_providers.py`, certains chemins d'erreur font
  `return typer.Exit(code=1)` au lieu de lever une exception (reliquat de
  l'ancien code CLI). Depuis `app.py`, ça peut donner un échec silencieux
  (le spinner se termine sans erreur visible alors que rien n'a été
  scrapé) plutôt qu'un message clair. À corriger si ça pose problème en
  pratique — remplacer ces `return typer.Exit(...)` par des exceptions
  levées normalement.
- `engine_and_database.py` supporte toujours MySQL, mais plus aucune
  interface ne l'expose (l'ancien `commands.py`/`db-init mysql` a été
  supprimé). Code mort à nettoyer ou à réactiver, au choix.
- `click` et `typer` restent importés dans `proxies_providers.py`
  uniquement pour `UsageError`/`typer.Exit` — dépendances qui pourraient
  être retirées si on nettoie les chemins d'erreur ci-dessus.
- Pas de tests automatisés sur ce projet (contrairement à `telecom_pulse_ca`
  qui a une suite pytest + CI GitHub Actions) — à considérer si le projet
  gagne en maturité.

## Historique des décisions (pour éviter de revenir en arrière par erreur)

- Le projet avait une couche CLI (Typer/Click, `commands.py`) et un serveur
  MCP (`mcp_server.py`, avec orchestrateur et diagnostic de sélecteurs
  CSS) — **retirés délibérément** à la demande de l'utilisateur pour
  réduire l'ambition et centraliser sur une seule interface Streamlit.
  Ne pas les recréer sans demande explicite.
- `db_credentials.json` (pour MySQL) était protégé en écriture (`chmod 600`)
  dans l'ancienne version CLI — cette protection n'existe plus car MySQL
  n'est plus exposé ; à réintroduire si MySQL revient dans l'interface.

## Prochaines étapes possibles (non commencées)

- Valider le scraping réel de bout en bout (proxies, parsing, insertion)
- Corriger les chemins d'erreur silencieux dans `proxies_providers.py`
- Ajouter des tests (au moins sur `data_quality.py`, logique pure sans
  dépendance réseau)
- Nettoyer le support MySQL mort ou le réintégrer proprement dans `app.py`
