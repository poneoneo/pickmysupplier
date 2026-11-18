#!/usr/bin/env bash
# Préparation initiale d'un VPS Ubuntu 24.04 neuf — à lancer UNE SEULE FOIS,
# en root :
#
#   DEPLOY_PUBKEY="ssh-ed25519 AAAA... github-deploy" bash setup-server.sh
#
# DEPLOY_PUBKEY = clé publique utilisée par la GitHub Action pour déployer.
# Elle est restreinte : elle ne peut lancer QUE deploy/deploy.sh (pas de
# shell, pas de tunnel), même si la clé privée fuitait.
set -euo pipefail

: "${DEPLOY_PUBKEY:?Définir DEPLOY_PUBKEY (clé publique de déploiement)}"
REPO_URL="https://github.com/poneoneo/pickmysupplier.git"
APP_DIR="/opt/pickmysupplier"
export DEBIAN_FRONTEND=noninteractive

echo "==> Mises à jour système"
apt-get update -q
apt-get upgrade -yq
apt-get install -yq ca-certificates curl git ufw unattended-upgrades

echo "==> Swap de 2 Go (filet de sécurité pour le build Docker sur les petits serveurs)"
if ! swapon --show | grep -q /swapfile; then
	fallocate -l 2G /swapfile
	chmod 600 /swapfile
	mkswap /swapfile >/dev/null
	swapon /swapfile
	grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "==> Mises à jour de sécurité automatiques"
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF

echo "==> Docker (dépôt apt officiel)"
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
	> /etc/apt/sources.list.d/docker.list
apt-get update -q
apt-get install -yq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker

echo "==> Pare-feu (SSH, HTTP, HTTPS uniquement)"
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable

echo "==> SSH : connexion par clé uniquement"
# Préfixe 00- : sshd garde la PREMIÈRE valeur lue pour chaque option, et les
# images cloud (ex. OVH) livrent un 50-cloud-init.conf avec
# "PasswordAuthentication yes" qui l'emporterait sur un fichier 99-.
cat > /etc/ssh/sshd_config.d/00-pickmysupplier.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
EOF
systemctl reload ssh

echo "==> Utilisateur de déploiement"
id deploy >/dev/null 2>&1 || useradd --create-home --shell /bin/bash deploy
usermod -aG docker deploy
install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
echo "command=\"${APP_DIR}/deploy/deploy.sh\",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty ${DEPLOY_PUBKEY}" \
	> /home/deploy/.ssh/authorized_keys
chown deploy:deploy /home/deploy/.ssh/authorized_keys
chmod 600 /home/deploy/.ssh/authorized_keys

echo "==> Code de l'app"
if [ ! -d "${APP_DIR}/.git" ]; then
	git clone --quiet "${REPO_URL}" "${APP_DIR}"
fi
chown -R deploy:deploy "${APP_DIR}"
chmod +x "${APP_DIR}/deploy/deploy.sh"

echo
echo "Terminé. Étapes suivantes :"
echo "  1. Créer ${APP_DIR}/deploy/.env (voir deploy/.env.example), propriétaire deploy, chmod 600"
echo "  2. sudo -u deploy ${APP_DIR}/deploy/deploy.sh"
