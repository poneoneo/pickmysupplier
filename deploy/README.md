# Déploiement sur VPS

Le site tourne sur un VPS (OVHcloud VPS-1, Beauharnois QC, Ubuntu 24.04) dans Docker, derrière
Caddy, qui gère le HTTPS automatiquement. Il ne se met jamais en veille,
contrairement à l'offre gratuite de Streamlit Community Cloud.

```
Internet ──443──▶ Caddy (HTTPS, certificat Let's Encrypt auto)
                    │
                    └──▶ app (Streamlit, port 8501 interne uniquement)
                           ├─ volume sessions/  (données par visiteur, purgées après 48 h)
                           └─ volume logs/
```

## Mises à jour : automatiques

Merger une PR sur `main` suffit :

1. la CI (`.github/workflows/ci.yml`) lance ruff et les tests ;
2. **si elle est verte**, `.github/workflows/deploy.yml` se connecte au
   serveur en SSH et lance `deploy/deploy.sh` (récupération de `main`, puis
   reconstruction de l'image et redémarrage) ;
3. le site est à jour 1 à 2 minutes plus tard.

Si la CI est rouge, rien n'est déployé et le site garde la version
précédente. Pour revenir en arrière, il suffit de faire `git revert` de la
PR fautive : le revert est redéployé de la même façon. L'historique des
déploiements se trouve dans l'onglet **Actions** de GitHub. Un déploiement
peut aussi être relancé à la main (« Run workflow » sur *Deploy*).

## Fichiers

| Fichier | Rôle |
|---|---|
| `Dockerfile` | Image de l'app (Python épinglé, utilisateur non-root, healthcheck) |
| `deploy/docker-compose.yml` | App + Caddy, redémarrage automatique |
| `deploy/Caddyfile` | HTTPS + reverse proxy (websockets inclus) |
| `deploy/.env.example` | Modèle du `deploy/.env` du serveur (jamais committé) |
| `deploy/setup-server.sh` | Préparation initiale du VPS (une seule fois) |
| `deploy/deploy.sh` | Mise à jour, lancée par la GitHub Action |

## Sécurité

- Seuls les ports 22, 80 et 443 sont ouverts (`ufw`). L'app n'est jamais
  exposée directement.
- Connexion SSH par clé uniquement ; les mots de passe sont désactivés.
- La clé de déploiement de GitHub est **restreinte** dans
  `authorized_keys` : elle ne peut lancer que `deploy/deploy.sh` (pas de
  shell, pas de tunnel).
- Les mises à jour de sécurité d'Ubuntu s'installent automatiquement
  (`unattended-upgrades`).
- Le serveur ne contient que `GROQ_API_KEY`. **Jamais**
  `SCRAPINGBEE_API_KEY` : chaque visiteur fournit sa propre clé.

## Installation initiale (une seule fois)

1. Créer le serveur (OVHcloud VPS, Ubuntu 24.04) et y ajouter ta clé SSH
   publique (utilisateur `ubuntu` chez OVH).
2. Faire pointer le domaine vers son IP (enregistrement DNS `A`). En
   attendant d'avoir un domaine, on peut utiliser `<ip>.sslip.io`.
3. Depuis ton PC, lancer la préparation du serveur (avec `sudo`) :
   `ssh ubuntu@<ip> "sudo DEPLOY_PUBKEY='<clé publique de déploiement>' bash -s" < deploy/setup-server.sh`
4. Créer `/opt/pickmysupplier/deploy/.env` à partir de `.env.example`
   (propriétaire `deploy`, `chmod 600`).
5. Lancer le premier déploiement : `sudo -u deploy /opt/pickmysupplier/deploy/deploy.sh`.
6. Dans GitHub (Settings → Secrets and variables → Actions), ajouter :
   - `DEPLOY_HOST` : l'IP ou le domaine du serveur ;
   - `DEPLOY_SSH_KEY` : la clé **privée** de déploiement ;
   - `DEPLOY_KNOWN_HOSTS` : la sortie de `ssh-keyscan <ip>`.

Tant que ces secrets n'existent pas, l'action *Deploy* se termine sans rien
faire, et la CI n'est pas bloquée.

## Commandes utiles (sur le serveur)

```bash
cd /opt/pickmysupplier
docker compose -f deploy/docker-compose.yml ps        # état
docker compose -f deploy/docker-compose.yml logs -f   # logs en direct
docker compose -f deploy/docker-compose.yml restart   # redémarrage
```
