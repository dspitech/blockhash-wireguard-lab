#!/usr/bin/env bash
# =========================================================
# BLOCKHash - LAB WireGuard
# Etape 6 (optionnelle) : gestion avancee d'un client en CLI
# Fine couche au-dessus de dashboard/backend/wgctl.py, le module
# qui porte toute la logique privilegiee (aussi utilise par le
# dashboard web, voir README section 7.6).
#
# Usage :
#   sudo ./06-manage-client.sh add <nom> [jours_expiration]
#   sudo ./06-manage-client.sh enable <nom>
#   sudo ./06-manage-client.sh disable <nom>
#   sudo ./06-manage-client.sh rename <ancien_nom> <nouveau_nom>
#   sudo ./06-manage-client.sh revoke <nom>
#   sudo ./06-manage-client.sh regenerate <nom>
#   sudo ./06-manage-client.sh expiry <nom> <AAAA-MM-JJ|none>
#   sudo ./06-manage-client.sh bandwidth <nom> <up_mbit|none> <down_mbit|none>
#   sudo ./06-manage-client.sh list
#   sudo ./06-manage-client.sh check-expirations
# =========================================================
set -euo pipefail

# Cherche wgctl.py d'abord a l'emplacement deploye, sinon en local
# (permet de tester ce wrapper avant meme d'avoir lance 03-install-dashboard.sh)
if [ -f /opt/blockhash-dashboard/backend/wgctl.py ]; then
  WGCTL="/opt/blockhash-dashboard/backend/wgctl.py"
else
  WGCTL="$(cd "$(dirname "${BASH_SOURCE[0]}")/../dashboard/backend" && pwd)/wgctl.py"
fi

usage() {
  sed -n '3,20p' "$0" | sed 's/^# \{0,1\}//'
  exit 1
}

[ "$#" -ge 1 ] || usage
ACTION="$1"; shift || true

pretty() {
  # Affiche joliment si jq est present, sinon affiche le JSON brut
  if command -v jq >/dev/null 2>&1; then jq .; else cat; fi
}

case "$ACTION" in
  add)
    [ "$#" -ge 1 ] || { echo "Usage : $0 add <nom> [jours_expiration]"; exit 1; }
    ARGS=(--name "$1"); [ "$#" -ge 2 ] && ARGS+=(--expires-days "$2")
    OUT=$(python3 "$WGCTL" add "${ARGS[@]}")
    echo "$OUT" | pretty
    CONF=$(echo "$OUT" | python3 -c "import json,sys;print(json.load(sys.stdin).get('conf_path',''))")
    if [ -n "$CONF" ] && [ -f "$CONF" ]; then
      echo ""
      echo "QR code (scan direct depuis l'app mobile WireGuard) :"
      qrencode -t ansiutf8 < "$CONF"
    fi
    ;;
  enable)      python3 "$WGCTL" enable --name "$1" | pretty ;;
  disable)     python3 "$WGCTL" disable --name "$1" | pretty ;;
  rename)      python3 "$WGCTL" rename --name "$1" --new-name "$2" | pretty ;;
  revoke)      python3 "$WGCTL" revoke --name "$1" | pretty ;;
  regenerate)  python3 "$WGCTL" regenerate --name "$1" | pretty ;;
  expiry)      python3 "$WGCTL" set-expiry --name "$1" --expires "$2" | pretty ;;
  bandwidth)   python3 "$WGCTL" set-bandwidth --name "$1" --bw-up "$2" --bw-down "$3" | pretty ;;
  list)        python3 "$WGCTL" list | pretty ;;
  check-expirations) python3 "$WGCTL" check-expirations | pretty ;;
  *) usage ;;
esac
