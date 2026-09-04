#!/usr/bin/env bash
# =========================================================
# BLOCKHash - LAB WireGuard
# Etape 1 : installation et configuration du serveur WireGuard
# A executer sur la VM Ubuntu (en root ou avec sudo)
# =========================================================
set -euo pipefail

WG_IF="wg0"
WG_PORT="51820"
WG_NET="10.66.66.0/24"
WG_SERVER_IP="10.66.66.1/24"
WG_DIR="/etc/wireguard"

echo "== 1. Mise a jour du systeme et installation des paquets =="
apt update && apt upgrade -y
apt install -y wireguard wireguard-tools qrencode ufw net-tools curl

echo "== 2. Activation du forwarding IPv4 =="
if ! grep -q "^net.ipv4.ip_forward=1" /etc/sysctl.conf; then
  echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
fi
sysctl -p

echo "== 3. Generation des cles du serveur =="
mkdir -p "$WG_DIR"
chmod 700 "$WG_DIR"
cd "$WG_DIR"

if [ ! -f server_private.key ]; then
  umask 077
  wg genkey | tee server_private.key | wg pubkey > server_public.key
fi

SERVER_PRIVATE_KEY=$(cat server_private.key)
SERVER_PUBLIC_KEY=$(cat server_public.key)

echo "== 4. Detection de l'interface reseau publique =="
DEFAULT_IF=$(ip route | awk '/^default/ {print $5; exit}')
echo "Interface publique detectee : $DEFAULT_IF"

echo "== 5. Creation du fichier de configuration serveur ($WG_IF.conf) =="
cat > "$WG_DIR/$WG_IF.conf" <<EOF
[Interface]
Address = $WG_SERVER_IP
ListenPort = $WG_PORT
PrivateKey = $SERVER_PRIVATE_KEY
SaveConfig = false

# NAT et forwarding : autorise les clients du tunnel a sortir vers Internet
PostUp = iptables -t nat -A POSTROUTING -o $DEFAULT_IF -j MASQUERADE
PostUp = iptables -A FORWARD -i $WG_IF -j ACCEPT
PostDown = iptables -t nat -D POSTROUTING -o $DEFAULT_IF -j MASQUERADE
PostDown = iptables -A FORWARD -i $WG_IF -j ACCEPT

# --- Les blocs [Peer] des clients seront ajoutes ci-dessous ---
# --- par le script 02-add-client.sh                        ---
EOF

chmod 600 "$WG_DIR/$WG_IF.conf"

echo "== 6. Ouverture du port dans le pare-feu local (ufw) =="
ufw allow 22/tcp comment "SSH"
ufw allow "$WG_PORT"/udp comment "WireGuard"
ufw --force enable
ufw status verbose

echo "== 7. Activation et demarrage du service WireGuard =="
systemctl enable wg-quick@"$WG_IF"
systemctl start wg-quick@"$WG_IF"
systemctl status wg-quick@"$WG_IF" --no-pager

echo ""
echo "=================================================="
echo " Serveur WireGuard installe et demarre avec succes"
echo "=================================================="
echo "Cle publique du serveur : $SERVER_PUBLIC_KEY"
echo "Port d'ecoute           : $WG_PORT/udp"
echo "Reseau du tunnel        : $WG_NET"
echo ""
echo "Verifiez l'etat du tunnel avec : sudo wg show"
echo "Ajoutez un client avec        : sudo ./02-add-client.sh <nom_client>"
