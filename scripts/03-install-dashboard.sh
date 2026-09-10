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
apt install -y python3 python3-venv python3-pip python3-dev gcc

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
WG_DIR=/etc/wireguard
WG_CONF_PATH=/etc/wireguard/wg0.conf
WG_LOG_CSV=/var/log/wireguard/tunnels.csv
FRONTEND_DIR=$APP_DIR/frontend
PORT=$DASHBOARD_PORT
# Passez a "false" pour repasser le dashboard en lecture seule (aucune
# regle sudoers wgctl.py necessaire) - voir README section 7.6.1.
CLIENT_MANAGEMENT_ENABLED=true
# Monitoring / alerting avances (voir README section 7.7)
METRICS_DB_PATH=/var/log/wireguard/blockhash.db
METRICS_DB_GROUP=$SERVICE_USER
AUDIT_LOG_PATH=/var/log/wireguard/audit.log
# Verrouillage anti force-brute sur l'authentification (voir README 7.10.4)
AUTH_MAX_ATTEMPTS=8
AUTH_LOCKOUT_SECONDS=300
SETTINGS_PATH=/etc/blockhash/dashboard-settings.json
ALERTS_CONFIG_PATH=/etc/blockhash/alerts-config.json
# Administration systeme avancee (voir README section 7.8) : sauvegardes,
# rotation de cles serveur, redemarrage du tunnel, export d'audit.
# Passez a "false" pour desactiver separement de CLIENT_MANAGEMENT_ENABLED
# (rayon d'impact plus large : redemarrage du service, rotation de cles).
SYSTEM_OPS_ENABLED=true
WG_EXPORT_DIR=/tmp/blockhash-exports
WG_MAX_BACKUPS=50
REPORTS_CONFIG_PATH=/etc/blockhash/reports-config.json
SERVERS_CONFIG_PATH=/etc/blockhash/servers.json
EOF
  chmod 600 /etc/blockhash/dashboard.env
fi

TOKEN_VALUE=$(grep DASHBOARD_TOKEN /etc/blockhash/dashboard.env | cut -d= -f2)

echo "== 4bis. Injection du jeton dans le frontend (pour que le navigateur soit deja authentifie) =="
cat > "$APP_DIR/frontend/js/config.js" <<EOF
// Fichier genere automatiquement par 03-install-dashboard.sh
// Permet au frontend d'appeler l'API sans configuration manuelle.
// Le jeton n'apporte qu'une defense complementaire : le dashboard n'est
// de toute facon joignable qu'en etant deja connecte au VPN WireGuard
// (voir 7bis. Caddy ci-dessus - ecoute uniquement sur l'IP privee du tunnel).
window.__BLOCKHASH_TOKEN__ = "${TOKEN_VALUE}";
EOF

echo "== 4ter. Reglages et configuration d'alertes (fichiers vides par defaut) =="
# Crees ici (pas seulement au premier appel de l'API) pour que les permissions
# soient correctes des le depart, meme si personne ne visite jamais l'onglet
# Parametres du dashboard.
if [ ! -f /etc/blockhash/dashboard-settings.json ]; then
  echo '{"online_threshold_sec": 180}' > /etc/blockhash/dashboard-settings.json
fi
if [ ! -f /etc/blockhash/alerts-config.json ]; then
  "$APP_DIR/venv/bin/python3" - <<PY
import json
json.dump(
    {"enabled": False, "rules": {"inactive_days": 7, "bandwidth_alert_mb_5min": None, "service_down": True}},
    open("/etc/blockhash/alerts-config.json", "w"),
    indent=2,
)
PY
fi
if [ ! -f /etc/blockhash/reports-config.json ]; then
  echo '{"weekly_enabled": false, "to_addr": ""}' > /etc/blockhash/reports-config.json
fi
if [ ! -f /etc/blockhash/servers.json ]; then
  echo '[]' > /etc/blockhash/servers.json
fi
chgrp "$SERVICE_USER" /etc/blockhash
chmod 770 /etc/blockhash
chown "$SERVICE_USER":"$SERVICE_USER" /etc/blockhash/dashboard-settings.json /etc/blockhash/alerts-config.json /etc/blockhash/reports-config.json /etc/blockhash/servers.json
chmod 640 /etc/blockhash/dashboard-settings.json /etc/blockhash/reports-config.json
chmod 600 /etc/blockhash/alerts-config.json /etc/blockhash/servers.json

echo "== 4quater. Attribution des permissions =="
# IMPORTANT : ce chown -R doit avoir lieu AVANT le verrouillage de wgctl.py
# ci-dessous (etape 5), sinon il ecraserait le root:root necessaire a la
# regle sudoers et redonnerait www-data en ecriture sur son propre script
# privilegie (elevation de privileges triviale).
chown -R "$SERVICE_USER":"$SERVICE_USER" "$APP_DIR"
chgrp "$SERVICE_USER" /etc/wireguard || true
chmod 750 /etc/wireguard || true
chgrp "$SERVICE_USER" /etc/wireguard/wg0.conf || true
chmod 640 /etc/wireguard/wg0.conf || true
# La base de metriques (samples de debit long terme) est ecrite par le cron
# root de 04-logging-monitoring.sh et lue par www-data (Flask) -> le groupe
# du fichier est ajuste apres chaque ecriture par store.py lui-meme
# (voir METRICS_DB_GROUP), mais on prepare le repertoire des maintenant.
mkdir -p /var/log/wireguard
chgrp "$SERVICE_USER" /var/log/wireguard || true
chmod 750 /var/log/wireguard || true
# Journal d'audit des actions sensibles (creation/revocation client, rotation
# de cles, redemarrage...) - pre-cree ici avec les bonnes permissions, sinon
# www-data (groupe en lecture seule sur le dossier, voir chmod 750 ci-dessus)
# ne pourrait pas creer ce fichier lui-meme au premier demarrage.
touch /var/log/wireguard/audit.log
chown "$SERVICE_USER":"$SERVICE_USER" /var/log/wireguard/audit.log
chmod 640 /var/log/wireguard/audit.log

echo "== 5. Autorisation sudo pour la lecture ET la gestion des clients =="
# gunicorn tourne sous www-data. Trois regles distinctes :
#  a) lecture seule : 'wg show wg0 dump' (etat live, non destructif)
#  b) gestion des clients : execution de wgctl.py en root, SEUL point
#     d'entree autorise a ecrire dans wg0.conf / appeler `wg set` / `tc`.
#  c) operations systeme : execution de wgops.py en root, SEUL point
#     d'entree autorise pour les sauvegardes/restaurations, la rotation
#     des cles serveur et le redemarrage du tunnel (voir README 7.8.1).
#     Rayon d'impact plus large que (b) -> desactivable separement via
#     SYSTEM_OPS_ENABLED, voir dashboard.env.
#     wgctl.py et wgops.py valident eux-memes chaque parametre et
#     n'acceptent que des actions connues : www-data ne peut donc pas
#     executer de commande arbitraire, seulement les operations exposees
#     par ces deux scripts.
# -> Voir README section 7.6.1 pour le detail des risques et alternatives
#    si vous preferez garder le dashboard strictement en lecture seule.
cat > /etc/sudoers.d/blockhash-dashboard <<EOF
$SERVICE_USER ALL=(root) NOPASSWD: /usr/bin/wg show wg0 dump
$SERVICE_USER ALL=(root) NOPASSWD: /usr/bin/python3 $APP_DIR/backend/wgctl.py *
$SERVICE_USER ALL=(root) NOPASSWD: /usr/bin/python3 $APP_DIR/backend/wgops.py *
EOF
chmod 440 /etc/sudoers.d/blockhash-dashboard
visudo -cf /etc/sudoers.d/blockhash-dashboard

# wgctl.py et wgops.py doivent appartenir a root et ne JAMAIS etre
# inscriptibles par www-data, sinon les regles sudoers ci-dessus
# permettraient a www-data de modifier le script qu'il execute ensuite
# en root (elevation de privileges triviale).
chown root:root "$APP_DIR/backend/wgctl.py" "$APP_DIR/backend/wgops.py"
chmod 750 "$APP_DIR/backend/wgctl.py" "$APP_DIR/backend/wgops.py"

# Alternative plus simple pour un LAB : autoriser www-data a lire wg0.conf
# et donner la capacite CAP_NET_ADMIN au binaire wg (voir README section 11).
setcap cap_net_admin+ep /usr/bin/wg || true

echo "== 5bis. Dependances pour la limitation de bande passante (tc / ifb, optionnel) =="
apt install -y iproute2 || true
modprobe ifb numifbs=1 2>/dev/null || true
grep -qxF "ifb" /etc/modules 2>/dev/null || echo "ifb" >> /etc/modules

echo "== 5ter. Verification automatique des expirations (cron quotidien) =="
# Appelle directement wgctl.py (deploye avec le dashboard) : desactive tout
# client dont la date d'expiration est depassee. Voir aussi
# scripts/07-check-expirations.sh pour lancer la meme verification a la main.
mkdir -p /var/log/wireguard
cat > /etc/cron.d/blockhash-expirations <<EOF
0 3 * * * root python3 $APP_DIR/backend/wgctl.py check-expirations >> /var/log/wireguard/expirations.log 2>&1
EOF
chmod 644 /etc/cron.d/blockhash-expirations

echo "== 5quater. Evaluation des regles d'alerte (cron toutes les 5 minutes) =="
# N'envoie rien tant que l'alerting n'est pas active (voir README 7.7.4 et
# l'onglet Alertes du dashboard) - la regle sudoers ci-dessus n'est PAS
# necessaire pour cette fonctionnalite (alerts.py ne fait que lire l'etat
# WireGuard deja autorise + son propre fichier de config sous /etc/blockhash).
cat > /etc/cron.d/blockhash-alerts <<EOF
*/5 * * * * root python3 $APP_DIR/backend/alerts.py check >> /var/log/wireguard/alerts.log 2>&1
EOF
chmod 644 /etc/cron.d/blockhash-alerts

echo "== 6. Verification finale des permissions sensibles =="
# Re-verifie apres coup que rien n'a pu regagner un droit d'ecriture sur
# les scripts privilegies (defense en profondeur si ce script est relance).
chown root:root "$APP_DIR/backend/wgctl.py" "$APP_DIR/backend/wgops.py"
chmod 750 "$APP_DIR/backend/wgctl.py" "$APP_DIR/backend/wgops.py"

echo "== 6bis. Rapport hebdomadaire par e-mail (cron, desactive par defaut) =="
# N'envoie rien tant que "weekly_enabled" n'est pas active depuis l'onglet
# Alertes du dashboard (voir README 7.9.3) - reutilise le canal e-mail deja
# configure pour les alertes, aucune regle sudoers supplementaire requise.
cat > /etc/cron.d/blockhash-weekly-report <<EOF
0 8 * * 1 root python3 $APP_DIR/backend/reports.py send-weekly >> /var/log/wireguard/reports.log 2>&1
EOF
chmod 644 /etc/cron.d/blockhash-weekly-report

echo "== 7. Creation du service systemd (gunicorn) =="
# --worker-class gthread --threads 4 (au lieu du sync worker par defaut) :
# necessaire pour le flux temps reel Server-Sent Events (/api/events/stream,
# voir README 7.10.3). Une connexion SSE reste ouverte plusieurs secondes ;
# avec des workers "sync" classiques, 2 onglets dashboard ouverts en meme
# temps suffiraient a saturer les 2 workers (-w 2) et a bloquer TOUTES les
# autres requetes (y compris les assets statiques). gthread permet a chaque
# worker de gerer plusieurs connexions concurrentes via des threads, sans
# dependance supplementaire (contrairement a gevent/eventlet).
#
# SECURITE (voir README 7.3bis) : gunicorn n'ecoute plus que sur 127.0.0.1.
# Il n'est plus jamais joignable directement, ni depuis le reseau public, ni
# meme depuis le tunnel WireGuard. Seul Caddy (etape 7bis) est autorise a
# lui parler, en loopback. C'est Caddy qui expose le dashboard sur l'IP
# privee du tunnel (10.66.66.1), avec TLS - donc uniquement accessible a
# quelqu'un deja connecte au VPN.
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
ExecStart=$APP_DIR/venv/bin/gunicorn -w 2 --worker-class gthread --threads 4 --timeout 120 -b 127.0.0.1:$DASHBOARD_PORT app:app
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable blockhash-dashboard
systemctl restart blockhash-dashboard

echo "== 7bis. Installation de Caddy (reverse proxy TLS, ecoute uniquement sur le tunnel WireGuard) =="
# Le dashboard n'est plus expose que sur l'IP privee du serveur WireGuard
# (WG_SERVER_IP, voir 01-install-wireguard-server.sh) : il faut donc etre
# deja connecte au VPN pour meme atteindre le port TLS. "tls internal"
# genere un certificat auto-signe localement (pas besoin de nom de domaine
# public) - le navigateur demandera une confirmation la premiere fois.
if ! command -v caddy >/dev/null 2>&1; then
  apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
  apt update
  apt install -y caddy
fi

WG_TUNNEL_IP="${WG_TUNNEL_IP:-10.66.66.1}"
DASHBOARD_TLS_PORT="${DASHBOARD_TLS_PORT:-443}"
cat > /etc/caddy/Caddyfile <<EOF
${WG_TUNNEL_IP}:${DASHBOARD_TLS_PORT} {
	tls internal
	reverse_proxy 127.0.0.1:${DASHBOARD_PORT}
	encode gzip
}
EOF
systemctl enable caddy
systemctl restart caddy

echo "== 8. Pare-feu local (ufw) =="
# Plus aucune regle necessaire pour le port $DASHBOARD_PORT : gunicorn est
# en loopback pur, ufw ne le voit meme pas. On autorise uniquement le port
# TLS de Caddy, et seulement pour les paquets arrivant PAR l'interface wg0
# (donc deja passes par le tunnel WireGuard - un attaquant sur le reseau
# public ne peut pas usurper "vient de wg0").
ufw allow in on wg0 to any port "$DASHBOARD_TLS_PORT" proto tcp comment "BLOCKHash Dashboard - VPN uniquement"

SERVER_ENDPOINT=$(curl -s ifconfig.me || curl -s ipinfo.io/ip)

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
echo " - La gestion des clients (ajout/activation/revocation/etc.) est"
echo "   activee depuis le dashboard. Les droits sudo de www-data ont ete"
echo "   etendus a wgctl.py (voir README section 7.6.1) - relisez cette"
echo "   section avant tout deploiement expose sur Internet."
echo " - Verifiez le service avec : sudo systemctl status blockhash-dashboard"
echo " - Monitoring avance (débit long terme, système, anomalies) et alerting"
echo "   configurable (email/Slack/Discord/Telegram) sont disponibles dans"
echo "   les onglets Monitoring et Alertes du dashboard - voir README 7.7."
echo "   L'alerting est DESACTIVE par defaut (rien n'est envoye tant que"
echo "   vous ne l'activez pas explicitement)."
echo " - Administration système (sauvegardes/restauration, rotation des clés"
echo "   serveur, redémarrage du tunnel, export d'audit, multi-serveurs) et"
echo "   reporting (export PDF/CSV, rapport hebdomadaire, vue Conformité)"
echo "   sont disponibles dans les onglets Système/Conformité - voir README"
echo "   section 7.8 et 7.9. Le rapport hebdomadaire est désactivé par défaut."
