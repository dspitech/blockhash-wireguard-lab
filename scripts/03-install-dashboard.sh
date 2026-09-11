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

echo "== 4. Generation des identifiants et du fichier d'environnement =="
mkdir -p /etc/blockhash
if [ ! -f /etc/blockhash/dashboard.env ]; then
  TOKEN=$(openssl rand -hex 24)
  DASH_USERNAME="${DASHBOARD_USERNAME:-admin}"
  DASH_PASSWORD="${DASHBOARD_PASSWORD:-$(openssl rand -base64 18 | tr -d '=+/')}"
  cat > /etc/blockhash/dashboard.env <<EOF
DASHBOARD_TOKEN=$TOKEN
DASHBOARD_USERNAME=$DASH_USERNAME
WG_INTERFACE=wg0
WG_DIR=/etc/wireguard
WG_CONF_PATH=/etc/wireguard/wg0.conf
WG_LOG_CSV=/var/log/wireguard/tunnels.csv
FRONTEND_DIR=$APP_DIR/frontend
PORT=$DASHBOARD_PORT
# Passez a "false" pour repasser le dashboard en lecture seule (aucune
# regle sudoers wgctl.py necessaire) - voir README section 10.1.1.
CLIENT_MANAGEMENT_ENABLED=true
# Monitoring / alerting avances (voir README section 10.2)
METRICS_DB_PATH=/var/log/wireguard/blockhash.db
METRICS_DB_GROUP=$SERVICE_USER
AUDIT_LOG_PATH=/var/log/wireguard/audit.log
# Verrouillage anti force-brute sur l'authentification (voir README 7.10.4)
AUTH_MAX_ATTEMPTS=8
AUTH_LOCKOUT_SECONDS=300
SETTINGS_PATH=/etc/blockhash/dashboard-settings.json
ALERTS_CONFIG_PATH=/etc/blockhash/alerts-config.json
# Administration systeme avancee (voir README section 10.3) : sauvegardes,
# rotation de cles serveur, redemarrage du tunnel, export d'audit.
# Passez a "false" pour desactiver separement de CLIENT_MANAGEMENT_ENABLED
# (rayon d'impact plus large : redemarrage du service, rotation de cles).
SYSTEM_OPS_ENABLED=true
WG_EXPORT_DIR=/tmp/blockhash-exports
WG_MAX_BACKUPS=50
REPORTS_CONFIG_PATH=/etc/blockhash/reports-config.json
SERVERS_CONFIG_PATH=/etc/blockhash/servers.json
EOF
  # Le hash du mot de passe est calcule a part (via le venv, une fois cree
  # ci-dessous) puis ajoute au fichier - evite une dependance a Python avant
  # l'etape 3 et garde le mot de passe en clair hors de tout fichier au repos.
  echo "$DASH_PASSWORD" > /run/blockhash-dashpw.tmp
  chmod 600 /run/blockhash-dashpw.tmp
  chmod 600 /etc/blockhash/dashboard.env
fi

TOKEN_VALUE=$(grep DASHBOARD_TOKEN /etc/blockhash/dashboard.env | cut -d= -f2)
DASH_USERNAME_VALUE=$(grep DASHBOARD_USERNAME /etc/blockhash/dashboard.env | cut -d= -f2)

echo "== 4bis. Hachage du mot de passe et verrouillage du frontend =="
# Contrairement a l'ancienne version, le jeton n'est PLUS injecte dans le
# HTML servi au navigateur : n'importe qui atteignant l'IP publique du
# dashboard obtiendrait sinon un acces immediat, sans avoir a s'authentifier.
# Desormais, config.js ne contient qu'une valeur vide ; le frontend affiche
# un ecran de connexion (identifiant + cle) qui echange ces identifiants
# contre le jeton via POST /api/login (voir dashboard/backend/app.py).
if [ -f /run/blockhash-dashpw.tmp ]; then
  DASH_PASSWORD_VALUE=$(cat /run/blockhash-dashpw.tmp)
  PW_HASH=$("$APP_DIR/venv/bin/python3" -c "import sys; from werkzeug.security import generate_password_hash; print(generate_password_hash(sys.argv[1]))" "$DASH_PASSWORD_VALUE")
  if ! grep -q '^DASHBOARD_PASSWORD_HASH=' /etc/blockhash/dashboard.env; then
    echo "DASHBOARD_PASSWORD_HASH=$PW_HASH" >> /etc/blockhash/dashboard.env
  fi
  shred -u /run/blockhash-dashpw.tmp 2>/dev/null || rm -f /run/blockhash-dashpw.tmp
fi
cat > "$APP_DIR/frontend/js/config.js" <<EOF
// Fichier genere automatiquement par 03-install-dashboard.sh
// Le jeton n'est plus injecte ici (voir etape 4bis) : le frontend l'obtient
// dynamiquement en se connectant via l'ecran de login (identifiant + cle).
window.__BLOCKHASH_TOKEN__ = "";
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
# 770 (pas 750) : le groupe www-data doit pouvoir non seulement LIRE mais
# aussi ECRIRE dans ce dossier, car gunicorn (execute en www-data) y cree
# lui-meme /var/log/wireguard/blockhash.db au tout premier appel a
# store.init_db() (voir dashboard/backend/store.py) - typiquement des le
# premier chargement du dashboard, avant meme que la tache cron de
# 04-logging-monitoring.sh ne soit passee. Avec 750 (bit d'ecriture group
# absent), cette creation echoue silencieusement et /api/health signale
# "metrics_db_reachable": false (verifiable avec 'curl -k https://127.0.0.1/healthz').
chmod 770 /var/log/wireguard || true
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

echo "== 7bis. Installation de Caddy (reverse proxy TLS, ecoute sur l'IP publique de la VM) =="
# Choix assume pour ce LAB (voir README 7.3bis, mis a jour) : le dashboard
# est desormais joignable directement via l'IP publique de la VM, SANS etre
# connecte au VPN WireGuard au prealable - la protection repose sur l'ecran
# de connexion (identifiant + cle, voir etape 4/4bis et app.py:/api/login),
# le verrouillage anti force-brute (AUTH_MAX_ATTEMPTS/AUTH_LOCKOUT_SECONDS)
# et le TLS de Caddy, PAS sur la position reseau du client. Combinez-la avec
# une regle NSG/ufw restreinte a votre IP admin des que possible (voir
# terraform/modules/network/main.tf : regle "AllowDashboard-Admin" et
# variable admin_source_ip) - c'est la seule couche qui limite reellement
# QUI peut meme atteindre l'ecran de connexion.
if ! command -v caddy >/dev/null 2>&1; then
  apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
  apt update
  apt install -y caddy
fi

DASHBOARD_TLS_PORT="${DASHBOARD_TLS_PORT:-443}"
# L'IP publique de la VM est STATIQUE (voir terraform/modules/compute/main.tf :
# azurerm_public_ip.this, allocation_method = "Static") - on peut donc la
# recuperer une fois ici et l'inscrire explicitement dans le Caddyfile.
# C'est indispensable : un bloc de site sans adresse (ex. ":443") ne dit pas
# a Caddy pour QUEL nom/IP emettre un certificat, et "tls internal" echoue
# alors silencieusement au moment du handshake (alerte TLS "internal error",
# visible avec 'curl -vk https://127.0.0.1/healthz'). En listant l'IP
# publique ET 127.0.0.1 comme adresses du site, Caddy genere immediatement
# au demarrage un certificat local valable pour les deux (pas besoin du mode
# "on_demand", qui necessite depuis Caddy 2.7+ un point de controle "ask"
# supplementaire - superflu ici puisque l'adresse est connue a l'avance et
# stable).
SERVER_ENDPOINT=$(curl -s ifconfig.me || curl -s ipinfo.io/ip)
cat > /etc/caddy/Caddyfile <<EOF
{
	# IMPORTANT (IP litterale + NAT cloud) : quand un client se connecte a
	# Caddy via une adresse IP (et non un nom de domaine), il n'envoie
	# aucun SNI dans la poignee de main TLS (RFC 6066 : une IP n'est pas
	# un nom de serveur valide). Sans SNI, Caddy ne peut pas faire
	# correspondre la connexion a un bloc de site et la poignee de main
	# echoue -> ERR_SSL_PROTOCOL_ERROR cote navigateur.
	# "default_sni" force Caddy a utiliser cette valeur comme nom de
	# serveur par defaut quand le client n'en fournit pas.
	default_sni ${SERVER_ENDPOINT}
}

https://${SERVER_ENDPOINT}:${DASHBOARD_TLS_PORT}, https://127.0.0.1:${DASHBOARD_TLS_PORT} {
	# IMPORTANT (cloud/NAT) : une adresse de site qui est une IP litterale
	# sert normalement AUSSI d'instruction d'ecoute (bind) chez Caddy, pas
	# seulement de critere de correspondance TLS/Host. Or sur Azure (comme
	# la plupart des clouds), l'IP publique de la VM n'est JAMAIS visible
	# sur son interface reseau : le systeme d'exploitation ne connait que
	# son IP privee, la traduction NAT vers l'IP publique se fait en amont,
	# dans l'infrastructure Azure. Sans "bind 0.0.0.0" ci-dessous, Caddy
	# tenterait de s'attacher litteralement a l'IP publique - une adresse
	# qui n'existe sur aucune interface locale - et ce listener echouerait
	# silencieusement : le dashboard resterait joignable en local
	# (127.0.0.1) mais totalement injoignable depuis l'exterieur (aucune
	# reponse, pas meme un avertissement de certificat).
	bind 0.0.0.0
	tls internal
	reverse_proxy 127.0.0.1:${DASHBOARD_PORT}
	encode gzip
}
EOF
systemctl enable caddy
systemctl restart caddy

echo "== 8. Pare-feu local (ufw) =="
# gunicorn reste en loopback pur (127.0.0.1) : seul Caddy, en TLS, est
# reellement joignable depuis l'exterieur. On ouvre ce port TLS a toutes les
# sources par defaut (acces via l'IP publique sans VPN, demande explicitement
# pour ce lab) - definissez ADMIN_SOURCE_IP (ex: "203.0.113.10/32") avant
# d'executer ce script pour le restreindre a une IP/CIDR precis, exactement
# comme la variable Terraform du meme nom (voir terraform/variables.tf).
if [ -n "${ADMIN_SOURCE_IP:-}" ]; then
  ufw allow from "$ADMIN_SOURCE_IP" to any port "$DASHBOARD_TLS_PORT" proto tcp comment "BLOCKHash Dashboard - IP admin"
else
  ufw allow "$DASHBOARD_TLS_PORT"/tcp comment "BLOCKHash Dashboard - ouvert (definissez ADMIN_SOURCE_IP pour restreindre)"
fi

echo ""
echo "=================================================="
echo " Dashboard BLOCKHash installe avec succes"
echo "=================================================="
echo "URL               : https://${SERVER_ENDPOINT}:${DASHBOARD_TLS_PORT}  (certificat auto-signe, confirmez l'exception dans le navigateur)"
echo "Identifiant        : ${DASH_USERNAME_VALUE}"
echo "Cle (mot de passe) : ${DASH_PASSWORD_VALUE:-[deja generee lors d_une installation precedente, voir /etc/blockhash/dashboard.env]}"
echo "Jeton d'API        : ${TOKEN_VALUE}"
echo ""
echo "IMPORTANT :"
echo " - Notez la cle ci-dessus MAINTENANT : elle n'est affichee qu'une fois"
echo "   et n'est jamais stockee en clair sur le disque (seul son hash l'est,"
echo "   dans /etc/blockhash/dashboard.env : DASHBOARD_PASSWORD_HASH)."
echo " - Le dashboard est joignable depuis l'IP publique de la VM SANS etre"
echo "   connecte au VPN - c'est voulu pour ce lab. Restreignez qui peut"
echo "   l'atteindre via ADMIN_SOURCE_IP (ufw, deja fait ci-dessus si defini)"
echo "   et la regle NSG Terraform 'AllowDashboard-Admin' (admin_source_ip)."
echo " - Le jeton d'API n'est utile que pour appeler l'API directement"
echo "   (curl -H \"X-API-Token: ...\"). Le frontend web, lui, ne le stocke"
echo "   qu'apres connexion reussie via l'ecran de login (identifiant + cle)."
echo " - Pour revenir a un acces reserve au VPN (ancien comportement), voir"
echo "   README section 7.4."
echo " - La gestion des clients (ajout/activation/revocation/etc.) est"
echo "   activee depuis le dashboard. Les droits sudo de www-data ont ete"
echo "   etendus a wgctl.py (voir README section 10.1.1) - relisez cette"
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
echo "   section 10.3 et 10.4. Le rapport hebdomadaire est désactivé par défaut."
