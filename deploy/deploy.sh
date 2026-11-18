#!/usr/bin/env bash
# Met le site à jour avec la dernière version de main.
#
# Lancé automatiquement par la GitHub Action "Deploy" après chaque CI verte
# sur main (la clé SSH de déploiement est restreinte à ce seul script, voir
# setup-server.sh). Peut aussi être lancé à la main sur le serveur.
set -euo pipefail

cd /opt/pickmysupplier

if [ "${DEPLOY_SCRIPT_UPDATED:-}" != "1" ]; then
	echo "==> Récupération de main"
	git fetch --quiet origin main
	git reset --hard --quiet origin/main
	echo "    version : $(git log -1 --format='%h %s')"
	# `git reset` vient peut-être de remplacer CE script : bash continuerait
	# d'exécuter l'ancienne version déjà ouverte, et toute modification de
	# deploy.sh ne s'appliquerait qu'au déploiement suivant. On relance
	# donc la version à jour (une seule fois, grâce à la variable).
	DEPLOY_SCRIPT_UPDATED=1 exec "$0" "$@"
fi

echo "==> Reconstruction et redémarrage"
# --wait : attend que le healthcheck de l'app soit vert ; sinon la commande
# échoue et la GitHub Action passe au rouge.
docker compose -f deploy/docker-compose.yml up -d --build --remove-orphans --wait

echo "==> Rechargement de la configuration Caddy"
# Caddy ne relit pas son Caddyfile tout seul, et `up` ne recrée pas son
# conteneur quand seul le contenu du fichier change. Le reload est sans
# coupure, et ne fait rien si la configuration est identique.
docker compose -f deploy/docker-compose.yml exec -T caddy \
	caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile

echo "==> Nettoyage des anciennes images"
docker image prune -f >/dev/null

echo "==> Déployé."
