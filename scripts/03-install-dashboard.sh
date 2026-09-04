#!/usr/bin/env bash
# =========================================================
# BLOCKHash - LAB WireGuard
# Etape 3 : installation du dashboard BLOCKHash (maison)
# Backend Flask + gunicorn (API) servant le frontend HTML/CSS/JS.
# A executer sur la VM, APRES avoir copie le dossier dashboard/
# a la racine du home (voir README section 7).
# =========================================================
set -euo pipefail

APP_DIR="/opt/blockhash-dashboard"
DASHBOARD_PORT="${1:-8080}"
SERVICE_USER="www-data"

if [ ! -d "./dashboard" ]; then
  echo "Erreur : le dossier ./dashboard est introuvable."
  echo "Transferez-le depuis votre poste avec :"
  echo "  scp -r dashboard/ wgadmin@<FQDN>:/home/wgadmin/"
  exit 1
fi

echo "== 1. Installation des dependances systeme =="
apt update
apt install -y python3 python3-venv python3-pip

echo "== 2. Copie de l'application vers $APP_DIR =="
mkdir -p "$APP_DIR"
cp -r ./dashboard/* "$APP_DIR/"

echo "== 3. Creation de l'environnement virtuel Python =="
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/backend/requirements.txt"

echo "== 4. Generation du jeton d'API et du fichier d'environnement =="
mkdir -p /etc/blockhash
if [ ! -f /etc/blockhash/dashboard.env ]; then
  TOKEN=$(openssl rand -hex 24)
  cat > /etc/blockhash/dashboard.env <<EOF
DASHBOARD_TOKEN=$TOKEN
WG_INTERFACE=wg0
WG_CONF_PATH=/etc/wireguard/wg0.conf
WG_LOG_CSV=/var/log/wireguard/tunnels.csv
FRONTEND_DIR=$APP_DIR/frontend
PORT=$DASHBOARD_PORT
EOF
  chmod 600 /etc/blockhash/dashboard.env
fi

echo "== 5. Autorisation sudo restreinte pour lire l'etat WireGuard =="
# gunicorn tourne sous www-data ; on l'autorise UNIQUEMENT a executer 'wg show'
cat > /etc/sudoers.d/blockhash-dashboard <<EOF
$SERVICE_USER ALL=(root) NOPASSWD: /usr/bin/wg show wg0 dump
EOF
chmod 440 /etc/sudoers.d/blockhash-dashboard

# Alternative plus simple pour un LAB : autoriser www-data a lire wg0.conf
# et donner la capacite CAP_NET_ADMIN au binaire wg (voir README section 11).
setcap cap_net_admin+ep /usr/bin/wg || true

echo "== 6. Attribution des permissions =="
chown -R "$SERVICE_USER":"$SERVICE_USER" "$APP_DIR"
chmod 640 /etc/wireguard/wg0.conf || true

echo "== 7. Creation du service systemd (gunicorn) =="
cat > /etc/systemd/system/blockhash-dashboard.service <<EOF
[Unit]
Description=BLOCKHash - Dashboard de supervision WireGuard
After=network.target wg-quick@wg0.service

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$APP_DIR/backend
EnvironmentFile=/etc/blockhash/dashboard.env
ExecStart=$APP_DIR/venv/bin/gunicorn -w 2 -b 0.0.0.0:$DASHBOARD_PORT app:app
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable blockhash-dashboard
systemctl restart blockhash-dashboard

echo "== 8. Ouverture du port dans le pare-feu local (ufw) =="
ufw allow "$DASHBOARD_PORT"/tcp comment "BLOCKHash Dashboard - admin only"

SERVER_ENDPOINT=$(curl -s ifconfig.me || curl -s ipinfo.io/ip)
TOKEN_VALUE=$(grep DASHBOARD_TOKEN /etc/blockhash/dashboard.env | cut -d= -f2)

echo ""
echo "=================================================="
echo " Dashboard BLOCKHash installe avec succes"
echo "=================================================="
echo "URL              : http://${SERVER_ENDPOINT}:${DASHBOARD_PORT}"
echo "Jeton d'API       : ${TOKEN_VALUE}"
echo ""
echo "IMPORTANT :"
echo " - Le port ${DASHBOARD_PORT} doit rester restreint a votre IP admin"
echo "   dans le NSG Terraform (variable admin_source_ip) et dans ufw."
echo " - Le jeton ci-dessus n'est utile que si vous appelez l'API"
echo "   directement (curl -H \"X-API-Token: ...\"). Le frontend web"
echo "   fonctionne sans jeton depuis la meme origine par defaut."
echo " - Verifiez le service avec : sudo systemctl status blockhash-dashboard"
