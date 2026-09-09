#!/usr/bin/env bash
# =========================================================
# BLOCKHash - LAB WireGuard
# Etape 7 (optionnelle) : desactivation automatique des clients expires
# Concu pour etre lance par cron (voir README section 7.6.4) :
#   0 3 * * * root /path/to/scripts/07-check-expirations.sh >> /var/log/wireguard/expirations.log 2>&1
# =========================================================
set -euo pipefail

if [ -f /opt/blockhash-dashboard/backend/wgctl.py ]; then
  WGCTL="/opt/blockhash-dashboard/backend/wgctl.py"
else
  WGCTL="$(cd "$(dirname "${BASH_SOURCE[0]}")/../dashboard/backend" && pwd)/wgctl.py"
fi

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
OUT=$(python3 "$WGCTL" check-expirations)
echo "[$TIMESTAMP] $OUT"
