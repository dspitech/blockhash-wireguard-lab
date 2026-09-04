#!/usr/bin/env bash
# =========================================================
# BLOCKHash - LAB WireGuard
# Etape 4 : mise en place de la journalisation des tunnels
# - Log CSV horodate de l'etat des peers (handshake, trafic)
# - Rotation automatique via logrotate
# - Tache cron toutes les 5 minutes
# =========================================================
set -euo pipefail

WG_IF="wg0"
LOG_DIR="/var/log/wireguard"
LOG_FILE="$LOG_DIR/tunnels.csv"
SNAPSHOT_SCRIPT="/usr/local/bin/wg-log-snapshot.sh"

echo "== 1. Creation du repertoire de logs =="
mkdir -p "$LOG_DIR"

echo "== 2. Creation du script de capture d'etat =="
cat > "$SNAPSHOT_SCRIPT" <<'EOF'
#!/usr/bin/env bash
# Capture l'etat courant du tunnel WireGuard au format CSV
WG_IF="wg0"
LOG_FILE="/var/log/wireguard/tunnels.csv"

if [ ! -f "$LOG_FILE" ]; then
  echo "timestamp,peer_public_key,endpoint,allowed_ips,last_handshake,rx_bytes,tx_bytes" > "$LOG_FILE"
fi

TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

wg show "$WG_IF" dump | tail -n +2 | while IFS=$'\t' read -r pubkey psk endpoint allowedips handshake rx tx keepalive; do
  echo "${TIMESTAMP},${pubkey},${endpoint},${allowedips},${handshake},${rx},${tx}" >> "$LOG_FILE"
done
EOF
chmod +x "$SNAPSHOT_SCRIPT"

echo "== 3. Installation de la tache cron (toutes les 5 minutes) =="
CRON_LINE="*/5 * * * * root $SNAPSHOT_SCRIPT"
if ! grep -qF "$SNAPSHOT_SCRIPT" /etc/crontab 2>/dev/null; then
  echo "$CRON_LINE" >> /etc/crontab
fi

echo "== 4. Configuration de la rotation des logs (logrotate) =="
cat > /etc/logrotate.d/wireguard <<EOF
$LOG_FILE {
    weekly
    rotate 12
    compress
    delaycompress
    missingok
    notifempty
    create 0640 root root
}
EOF

echo "== 5. Activation des logs systemd detailles pour wg-quick =="
mkdir -p /etc/systemd/system/wg-quick@${WG_IF}.service.d
cat > /etc/systemd/system/wg-quick@${WG_IF}.service.d/override.conf <<EOF
[Service]
StandardOutput=journal
StandardError=journal
EOF
systemctl daemon-reload

# Premiere capture immediate
"$SNAPSHOT_SCRIPT"

echo ""
echo "=================================================="
echo " Journalisation mise en place avec succes"
echo "=================================================="
echo "Log CSV des tunnels   : $LOG_FILE"
echo "Frequence de capture  : toutes les 5 minutes (cron)"
echo "Logs systemd (kernel) : journalctl -u wg-quick@${WG_IF} -f"
echo "Rotation              : hebdomadaire, 12 semaines conservees"
echo ""
echo "Consultez l'etat en direct avec : sudo wg show"
echo "Consultez l'historique CSV avec : column -s, -t < $LOG_FILE | less"
