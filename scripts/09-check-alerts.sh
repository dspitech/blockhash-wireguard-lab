#!/usr/bin/env bash
# =========================================================
# BLOCKHash - LAB WireGuard
# Etape 7 (avancee, optionnelle) : evaluation des regles d'alerte
# Concu pour etre lance par cron toutes les 5 minutes (voir README
# section 7.7.4) :
#   */5 * * * * root /path/to/scripts/09-check-alerts.sh >> /var/log/wireguard/alerts.log 2>&1
#
# N'envoie rien tant que l'alerting n'est pas active depuis le dashboard
# (Parametres -> Alertes -> Activer) ou via PATCH /api/alerts/config.
# =========================================================
set -euo pipefail

if [ -f /opt/blockhash-dashboard/backend/alerts.py ]; then
  ALERTS_PY="/opt/blockhash-dashboard/backend/alerts.py"
else
  ALERTS_PY="$(cd "$(dirname "${BASH_SOURCE[0]}")/../dashboard/backend" && pwd)/alerts.py"
fi

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
OUT=$(python3 "$ALERTS_PY" check)
echo "[$TIMESTAMP] $OUT"
