# Contribuer à PickMySupplier

Ce document décrit les conventions de commits et de branches utilisées sur
ce projet. Elles s'appliquent à **tous** les commits, y compris ceux de
l'auteur principal.

## Convention de commits (Gitmoji)

Chaque commit commence par un emoji qui indique la nature du changement,
suivi d'un type court et d'une description en français, à l'impératif ou au
présent :

```
<emoji> <type>: <description>
```

Exemples :

```
✨ feat: ajout de la commande scan
🐛 fix: correction du parsing JSON
```

### Table des emojis

| Emoji | Code                | Type       | Usage                                    |
|-------|----------------------|------------|-------------------------------------------|
| ✨    | `:sparkles:`         | `feat`     | Nouvelle fonctionnalité                   |
| 🐛    | `:bug:`               | `fix`      | Correction de bug                         |
| 🔥    | `:fire:`              | `remove`   | Suppression de code ou de fichiers        |
| ♻️    | `:recycle:`           | `refactor` | Refactoring (sans changement de comportement) |
| 🧪    | `:test_tube:`         | `test`     | Ajout ou modification de tests            |
| 📝    | `:memo:`              | `docs`     | Documentation                             |
| 🎨    | `:art:`               | `style`    | Formatage, structure du code              |
| ⚡    | `:zap:`               | `perf`     | Amélioration de performance               |
| 🔧    | `:wrench:`            | `chore`    | Configuration (CI, outils, dépendances)   |
| 🚀    | `:rocket:`            | `deploy`   | Déploiement                               |
| 🔒    | `:lock:`              | `security` | Sécurité                                  |
| ⬆️    | `:arrow_up:`          | `upgrade`  | Montée de version d'une dépendance        |

Un commit ne doit contenir qu'**un seul type de changement**. Si un commit
mélange plusieurs types (ex : un refactor et un test), il vaut mieux le
scinder en plusieurs commits.

## Convention de branches

| Préfixe      | Usage                                  | Exemple                          |
|--------------|------------------------------------------|-----------------------------------|
| `feature/`   | Nouvelle fonctionnalité                  | `feature/nl-search-filters`       |
| `fix/`       | Correction de bug                        | `fix/json-parsing-crash`          |
| `refactor/`  | Refactoring                              | `refactor/proxies-error-handling` |
| `test/`      | Ajout de tests                           | `test/data-quality-checks`        |
| `chore/`     | Maintenance, config, dépendances         | `chore/ci-pipeline`               |

Le nom après le préfixe est en `kebab-case`, court et descriptif.

## Workflow

1. Créer une branche depuis `main` avec le préfixe adapté.
2. Committer avec la convention Gitmoji ci-dessus (un commit = un changement
   logique).
3. Ouvrir une Pull Request vers `main` (le template la pré-remplit
   automatiquement).
4. La CI (lint + tests) doit passer avant merge.
5. Merger uniquement après review.
