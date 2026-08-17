# PickMySupplier

[![CI](https://github.com/poneoneo/pickmysupplier/actions/workflows/ci.yml/badge.svg)](https://github.com/poneoneo/pickmysupplier/actions/workflows/ci.yml)

Pipeline de sourcing B2B : scrape une marketplace de produits/fournisseurs,
valide les données, les stocke, puis permet de choisir le meilleur
fournisseur sur la base d'insights générés — recherche en langage naturel et
visualisations, le tout dans une application Streamlit unique.

> Projet portfolio personnel, non destiné à la commercialisation. Voir
> `CLAUDE.md` pour le contexte complet du projet.

## Lancer le projet

```bash
pip install -r requirements.txt
streamlit run app.py
```

Nécessite un fichier `.env` à la racine avec `BRIGHT_DATA_API_KEY`,
`SCRAPINGBEE_API_KEY`, `GROQ_API_KEY` (voir `CLAUDE.md` pour le détail).

## Développement

```bash
pip install -r requirements-dev.txt
python -m pytest        # tests
python -m ruff check .  # lint
```

Voir [CONTRIBUTING.md](CONTRIBUTING.md) pour la convention de commits et de
branches utilisée sur ce projet.

## Stack technique

Python · Streamlit · Playwright · SQLModel/SQLAlchemy · Plotly · Groq
(recherche en langage naturel — filtre/tri structuré, pas de code généré)
