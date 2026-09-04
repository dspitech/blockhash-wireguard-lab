#!/usr/bin/env bash
# =========================================================
# BLOCKHash - LAB WireGuard
# Etape 2 : ajout d'un client (peer) au serveur WireGuard
# Usage : sudo ./02-add-client.sh <nom_client>
# =========================================================
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "Usage : $0 <nom_client>"
  exit 1
fi

CLIENT_NAME="$1"
WG_IF="wg0"
WG_DIR="/etc/wireguard"
CLIENTS_DIR="$WG_DIR/clients"
WG_PORT="51820"
WG_SERVER_SUBNET="10.66.66"

mkdir -p "$CLIENTS_DIR"
cd "$WG_DIR"

# --- Détermine la prochaine IP disponible dans le tunnel (.2, .3, ...) ---
LAST_OCTET=$(grep -oP "AllowedIPs = ${WG_SERVER_SUBNET}\.\K[0-9]+" "$WG_IF.conf" 2>/dev/null | sort -n | tail -1 || true)
NEXT_OCTET=$(( ${LAST_OCTET:-1} + 1 ))
CLIENT_IP="${WG_SERVER_SUBNET}.${NEXT_OCTET}/32"

echo "== Generation des cles pour le client '$CLIENT_NAME' =="
umask 077
wg genkey | tee "$CLIENTS_DIR/${CLIENT_NAME}_private.key" | wg pubkey > "$CLIENTS_DIR/${CLIENT_NAME}_public.key"
wg genpsk > "$CLIENTS_DIR/${CLIENT_NAME}_preshared.key"

CLIENT_PRIVATE_KEY=$(cat "$CLIENTS_DIR/${CLIENT_NAME}_private.key")
CLIENT_PUBLIC_KEY=$(cat "$CLIENTS_DIR/${CLIENT_NAME}_public.key")
CLIENT_PSK=$(cat "$CLIENTS_DIR/${CLIENT_NAME}_preshared.key")
SERVER_PUBLIC_KEY=$(cat "$WG_DIR/server_public.key")

# Recupere automatiquement l'IP publique / FQDN de la VM
SERVER_ENDPOINT=$(curl -s ifconfig.me || curl -s ipinfo.io/ip)

echo "== Ajout du peer dans la configuration serveur =="
cat >> "$WG_DIR/$WG_IF.conf" <<EOF

[Peer]
# Client : $CLIENT_NAME
PublicKey = $CLIENT_PUBLIC_KEY
PresharedKey = $CLIENT_PSK
AllowedIPs = $CLIENT_IP
EOF

echo "== Generation du fichier de configuration client =="
cat > "$CLIENTS_DIR/${CLIENT_NAME}.conf" <<EOF
[Interface]
PrivateKey = $CLIENT_PRIVATE_KEY
Address = $CLIENT_IP
DNS = 1.1.1.1

[Peer]
PublicKey = $SERVER_PUBLIC_KEY
PresharedKey = $CLIENT_PSK
Endpoint = ${SERVER_ENDPOINT}:${WG_PORT}
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
EOF

chmod 600 "$CLIENTS_DIR/${CLIENT_NAME}.conf"

echo "== Application de la configuration a chaud (sans coupure du tunnel) =="
wg syncconf "$WG_IF" <(wg-quick strip "$WG_IF")

echo ""
echo "=================================================="
echo " Client '$CLIENT_NAME' cree avec succes"
echo "=================================================="
echo "IP attribuee     : $CLIENT_IP"
echo "Fichier config   : $CLIENTS_DIR/${CLIENT_NAME}.conf"
echo ""
echo "Recuperez ce fichier sur votre poste (scp) et importez-le"
echo "dans l'application WireGuard (Windows/macOS/Linux/mobile)."
echo ""
echo "QR code (scan direct depuis l'app mobile WireGuard) :"
qrencode -t ansiutf8 < "$CLIENTS_DIR/${CLIENT_NAME}.conf"
