# Isolation des données par session (scraping public multi-visiteurs)

Status: approuvé en chat (sections 1–2), en attente de revue de la version écrite.

## 1. Contexte

L'app est hébergée publiquement depuis le 2026-08-20
(https://pickmysupplier.streamlit.app/) sur Streamlit Community Cloud, qui
fait tourner **un seul process Python partagé par tous les visiteurs**, avec
un disque local qui persiste entre les visites (pas un bac à sable par
visiteur).

Le code de scraping/stockage a été écrit à l'origine pour un usage
mono-utilisateur (l'auteur, en local). Deux mécanismes qui étaient corrects
dans ce contexte deviennent des fuites de données une fois le site public :

1. **`discover_databases()`** (`sourcing_intel_cli/datasets.py:31`) fait un
   `glob` de tous les `sourcing_intel_*.sqlite` à la racine du projet. Sur
   l'hébergement partagé, ça remonte les bases créées par **n'importe quel
   visiteur** — le sélecteur de jeu de données de la page Explorer permet
   donc à un visiteur de parcourir les recherches (et les données scrapées
   avec la clé API d'un autre) de n'importe qui d'autre.
2. **`HTML_PAGE_RESULT`** (`sourcing_intel_cli/proxies_utils.py:1`) est une
   liste globale au module, partagée par tout le process. Deux scrapes
   simultanés (deux visiteurs différents) mutent la même liste — risque de
   mélange de données entre deux scrapes concurrents, indépendamment du
   problème de stockage partagé.

Confirmé avec l'utilisateur : la clé ScrapingBee elle-même n'est pas stockée
globalement (elle est lue depuis `st.session_state` à chaque appel) — le
problème est le résultat du scrape fait avec cette clé, qui atterrit sur un
disque visible par le prochain visiteur.

Discuté et explicitement écarté : ajouter un système de comptes/login. Le
projet reste un portfolio non-commercial (voir CLAUDE.md), avec un historique
délibéré de réduction d'ambition (CLI, serveur MCP, support MySQL retirés).
Un système d'authentification est un chantier disproportionné pour corriger
une fuite de données — la solution retenue reste dans l'esprit du projet :
aucun compte, isolation par session Streamlit uniquement.

## 2. Objectifs

- Un visiteur ne voit jamais les données scrapées, les CSV téléchargeables,
  ni l'usage de clé API d'un autre visiteur.
- Le sélecteur "mes recherches précédentes" de la page Explorer reste
  disponible, mais scopé à la session du visiteur courant.
- Le jeu de données de démo (`sourcing_intel_demo.sqlite`, synthétique,
  seed=42, identique pour tout le monde) reste partagé — pas de risque de
  fuite, pas de raison de le scoper.
- Le bug de concurrence sur `HTML_PAGE_RESULT` est corrigé, indépendamment du
  reste.
- Les fichiers de session inactifs ne s'accumulent pas indéfiniment sur le
  disque partagé.

## 3. Non-goals

- Pas de comptes utilisateurs, pas d'authentification, pas de login/signup —
  explicitement écarté (voir Contexte).
- Pas de vrai scheduler/cron pour le nettoyage — une solution best-effort
  suffit pour un portfolio à trafic modeste.
- Pas de migration active des fichiers déjà présents sur le disque de prod
  (créés avant ce fix) — ils deviennent simplement invisibles après
  déploiement (voir section 6), et seront purgés au prochain redémarrage du
  disque éphémère de Streamlit Cloud.
- Pas de changement au pipeline de scraping/parsing/validation lui-même (URLs
  ciblées, parsing HTML, agent qualité) — uniquement où/comment les résultats
  sont stockés.

## 4. Architecture & flux de données

**Identifiant de session** : au chargement de l'app, génération d'un
`session_id` unique et stable pour la durée de la session Streamlit :

```python
import uuid
session_id = st.session_state.setdefault("session_id", uuid.uuid4().hex[:12])
```

**Layout de stockage**, tout sous un répertoire par session au lieu de la
racine partagée :

| Avant (partagé) | Après (par session) |
|---|---|
| `scraped_pages/<slug>/` | `sessions/<session_id>/scraped_pages/<slug>/` |
| `sourcing_intel_<slug>.sqlite` (racine) | `sessions/<session_id>/db/sourcing_intel_<slug>.sqlite` |
| `sourcing_intel_demo.sqlite` (racine) | **inchangé** — reste partagé, synthétique |

**`page_scraper()`** (`app.py`) : `save_in_folder` et le `db_name` passé à
`_validate_and_insert` sont préfixés par `sessions/{session_id}/`.

**`page_explorer()`** (`app.py`) : `discover_databases()` est appelé avec
`root=Path(f"sessions/{session_id}/db")` (uniquement les recherches de ce
visiteur) et le résultat est complété par `sourcing_intel_demo.sqlite` à la
racine s'il existe, pour que le jeu de démo reste sélectionnable par tous.

**`create_db_engine`** (`sourcing_intel_cli/engine_and_database.py`) :
ajout d'un `Path(f"{db_name}.sqlite").parent.mkdir(parents=True,
exist_ok=True)` avant `create_engine(...)` — SQLite ne crée pas les
répertoires parents tout seul, et `sessions/<id>/db/` n'existe pas encore à
la première écriture d'une session donnée.

**Correction de `HTML_PAGE_RESULT`** (`sourcing_intel_cli/proxies_providers.py`,
`sourcing_intel_cli/proxies_utils.py`) : `sync_scraper` déclare une liste
locale (`html_pages: list[str] = []`) au lieu de muter le module-global
`HTML_PAGE_RESULT`, et la passe directement à `write_to_disk`. Le global
`HTML_PAGE_RESULT` et son import dans `proxies_providers.py` sont retirés
(code mort une fois la liste locale en place).

## 5. Nettoyage des sessions orphelines

Sans nettoyage, `sessions/` grossit indéfiniment (chaque visite laisse un
dossier, même après que le visiteur soit reparti). Pas de scheduler dédié —
une fonction dans `datasets.py` :

```python
def cleanup_stale_sessions(root: Path = Path("sessions"), max_age_hours: int = 48) -> None:
    """Delete session directories whose newest file is older than max_age_hours."""
```

Appelée au chargement de l'app, enveloppée dans
`st.cache_resource(ttl=3600)` : `cache_resource` est un cache **partagé par
tout le process** (pas par session), donc avec un TTL d'1h la fonction
s'exécute au plus une fois par heure pour l'ensemble du site, quel que soit
le nombre de visiteurs simultanés — aucune infra supplémentaire.

## 6. Fichiers déjà présents sur le disque de production

Le site est en ligne depuis le 2026-08-20 ; des fichiers `sourcing_intel_*.sqlite`
et `scraped_pages/*` créés par de vrais visiteurs avant ce fix sont
probablement déjà sur le disque partagé. Après déploiement, ils deviennent
simplement invisibles (`discover_databases` ne regarde plus la racine pour
les recherches live) — aucune suppression active nécessaire. Ils seront
purgés au prochain redémarrage/redeploy du disque éphémère de Streamlit
Community Cloud.

## 7. Tests

- `test_proxies_providers.py` : adapter les tests de `sync_scraper` pour
  vérifier qu'il n'y a plus de dépendance au module-global `HTML_PAGE_RESULT`
  (liste locale retournée/passée à `write_to_disk`), et qu'un scrape
  concurrent simulé (deux appels successifs avec des `save_in` différents)
  ne mélange pas leurs résultats.
- `test_engine_and_database.py` : vérifier que `create_db_engine` crée les
  répertoires parents manquants (`db_name` avec sous-dossiers inexistants).
- Nouveau : test pour `discover_databases(root=...)` scopé — ne remonte pas
  les fichiers d'un autre `root`.
- Nouveau : test pour `cleanup_stale_sessions` — un dossier de session vieux
  de plus de `max_age_hours` est supprimé, un dossier récent est conservé.

## 8. Portée explicitement exclue de ce cycle (problème séparé)

L'utilisateur a signalé un second problème indépendant, à traiter dans un
cycle brainstorming/spec séparé : les champs des tables `Product`/`Supplier`
sont sous-exploités dans l'UI, et les exemples de questions en langage
naturel ne sont pas assez parlants/engageants pour montrer l'étendue de ce
que l'app peut faire. Non traité ici.
