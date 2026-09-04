#!/usr/bin/env bash
# =========================================================
# BLOCKHash - LAB WireGuard
# Etape 5 (optionnelle) : revocation d'un client
# Usage : sudo ./05-revoke-client.sh <nom_client>
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

if [ ! -f "$CLIENTS_DIR/${CLIENT_NAME}_public.key" ]; then
  echo "Client inconnu : $CLIENT_NAME"
  exit 1
fi

CLIENT_PUBLIC_KEY=$(cat "$CLIENTS_DIR/${CLIENT_NAME}_public.key")

echo "== Retrait du peer en temps reel (sans coupure du service) =="
wg set "$WG_IF" peer "$CLIENT_PUBLIC_KEY" remove

echo "== Suppression du bloc [Peer] dans $WG_IF.conf =="
python3 - "$WG_DIR/$WG_IF.conf" "$CLIENT_NAME" <<'PYEOF'
import sys, re
path, name = sys.argv[1], sys.argv[2]
with open(path) as f:
    content = f.read()
pattern = re.compile(
    r"\n\[Peer\]\n# Client : " + re.escape(name) + r"\n(?:.*\n)*?(?=\n\[Peer\]|\Z)"
)
content = pattern.sub("\n", content)
with open(path, "w") as f:
    f.write(content)
PYEOF

echo "== Archivage des cles du client revoque =="
mkdir -p "$CLIENTS_DIR/revoked"
mv "$CLIENTS_DIR/${CLIENT_NAME}"* "$CLIENTS_DIR/revoked/" 2>/dev/null || true

echo ""
echo "Client '$CLIENT_NAME' revoque avec succes."
echo "Verification : sudo wg show"
