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
# Capture l'etat courant du tunnel WireGuard toutes les 5 minutes et
# alimente :
#   - la base SQLite de store.py (table `logs`) : SOURCE DE LECTURE du
#     journal des connexions affiche/pagine dans le dashboard (voir
#     README 7.10.1) ainsi que des metriques de debit long terme
#     (table `samples`, selecteur 1h/24h/7j/30j) ;
#   - le fichier texte $LOG_FILE ci-dessous, en parallele : PLUS LU par
#     le dashboard, mais conserve comme trace brute grep/tail-able sans
#     outillage (audit rapide en SSH, export vers un autre systeme).
WG_IF="wg0"
LOG_FILE="/var/log/wireguard/tunnels.csv"
STORE_PY="/opt/blockhash-dashboard/backend/store.py"

if [ ! -f "$LOG_FILE" ]; then
  echo "timestamp,peer_public_key,endpoint,allowed_ips,last_handshake,rx_bytes,tx_bytes" > "$LOG_FILE"
fi

TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
DUMP=$(wg show "$WG_IF" dump | tail -n +2)

echo "$DUMP" | while IFS=$'\t' read -r pubkey psk endpoint allowedips handshake rx tx keepalive; do
  [ -n "$pubkey" ] || continue
  echo "${TIMESTAMP},${pubkey},${endpoint},${allowedips},${handshake},${rx},${tx}" >> "$LOG_FILE"
done

# Ingestion SQLite (logs + samples) best-effort : si le dashboard n'est pas
# (encore) installe, ou si store.py echoue pour une raison quelconque, la
# capture CSV ci-dessus n'est jamais impactee (elle est deja terminee a ce
# stade) - le journal du dashboard sera simplement en retard d'un cycle.
if [ -f "$STORE_PY" ] && [ -n "$DUMP" ]; then
  echo "$DUMP" | python3 "$STORE_PY" ingest --ts "$(date +%s)" >/dev/null 2>&1 || true
fi
EOF
chmod +x "$SNAPSHOT_SCRIPT"

echo "== 3. Installation de la tache cron (toutes les 5 minutes) =="
CRON_LINE="*/5 * * * * root $SNAPSHOT_SCRIPT"
if ! grep -qF "$SNAPSHOT_SCRIPT" /etc/crontab 2>/dev/null; then
  echo "$CRON_LINE" >> /etc/crontab
fi

# Purge quotidienne de la base de metriques long terme (35 jours de retention
# par defaut, voir METRICS_RETENTION_DAYS dans store.py) - sans effet si le
# dashboard n'est pas installe (store.py absent).
PRUNE_LINE="30 3 * * * root [ -f /opt/blockhash-dashboard/backend/store.py ] && python3 /opt/blockhash-dashboard/backend/store.py prune >/dev/null 2>&1"
if ! grep -qF "store.py prune" /etc/crontab 2>/dev/null; then
  echo "$PRUNE_LINE" >> /etc/crontab
fi

# Sauvegardes planifiees (desactivees par defaut - reglage 'backup_schedule'
# dans le dashboard : disabled/daily/weekly/monthly). Tourne tous les jours a
# 4h ; wgops.py act_auto_backup s'auto-limite lui-meme selon le planning
# configure (voir wgops.py) plutot que de reecrire dynamiquement cette ligne
# de cron - www-data n'a ainsi jamais besoin d'ecrire dans /etc/crontab.
AUTO_BACKUP_LINE="0 4 * * * root [ -f /opt/blockhash-dashboard/backend/wgops.py ] && python3 /opt/blockhash-dashboard/backend/wgops.py auto-backup >/dev/null 2>&1"
if ! grep -qF "wgops.py auto-backup" /etc/crontab 2>/dev/null; then
  echo "$AUTO_BACKUP_LINE" >> /etc/crontab
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
