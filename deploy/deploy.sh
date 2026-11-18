#!/usr/bin/env bash
# Met le site à jour avec la dernière version de main.
#
# Lancé automatiquement par la GitHub Action "Deploy" après chaque CI verte
# sur main (la clé SSH de déploiement est restreinte à ce seul script, voir
# setup-server.sh). Peut aussi être lancé à la main sur le serveur.
set -euo pipefail

cd /opt/pickmysupplier

echo "==> Récupération de main"
git fetch --quiet origin main
git reset --hard --quiet origin/main
echo "    version : $(git log -1 --format='%h %s')"

echo "==> Reconstruction et redémarrage"
# --wait : attend que le healthcheck de l'app soit vert ; sinon la commande
# échoue et la GitHub Action passe au rouge.
docker compose -f deploy/docker-compose.yml up -d --build --remove-orphans --wait

echo "==> Nettoyage des anciennes images"
docker image prune -f >/dev/null

echo "==> Déployé."
