#!/usr/bin/env python3
"""
BLOCKHash - Dashboard WireGuard
API Flask servant les données de supervision (tunnels, journal des
connexions, débit) à l'interface web statique (dashboard/frontend).

Endpoints :
  GET /api/overview   -> etat complet (stats + peers + logs + serie de debit)
  GET /api/peers       -> liste des peers avec statut en direct (wg show)
  GET /api/logs         -> journal des connexions (tunnels.csv), pagine
  GET /healthz          -> sonde de disponibilite

Authentification : header "X-API-Token" compare a la variable
d'environnement DASHBOARD_TOKEN (voir /etc/blockhash/dashboard.env).
Laisser DASHBOARD_TOKEN vide desactive l'authentification (LAB/demo uniquement).
"""

import csv
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

WG_INTERFACE = os.environ.get("WG_INTERFACE", "wg0")
WG_CONF_PATH = Path(os.environ.get("WG_CONF_PATH", "/etc/wireguard/wg0.conf"))
LOG_CSV_PATH = Path(os.environ.get("WG_LOG_CSV", "/var/log/wireguard/tunnels.csv"))
DASHBOARD_TOKEN = os.environ.get("DASHBOARD_TOKEN", "")
FRONTEND_DIR = Path(os.environ.get("FRONTEND_DIR", Path(__file__).resolve().parent.parent / "frontend"))
HANDSHAKE_ONLINE_THRESHOLD_SEC = 180  # peer considere "en ligne" si handshake < 3 min

app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="")


# ------------------------------------------------------------------
# Authentification
# ------------------------------------------------------------------
def check_auth():
    if not DASHBOARD_TOKEN:
        return True
    return request.headers.get("X-API-Token") == DASHBOARD_TOKEN


@app.before_request
def enforce_auth():
    if request.path.startswith("/api/") and not check_auth():
        return jsonify({"error": "unauthorized"}), 401


# ------------------------------------------------------------------
# Extraction des noms de clients depuis wg0.conf
# (le script 02-add-client.sh insere un commentaire "# Client : nom"
#  juste avant chaque bloc [Peer])
# ------------------------------------------------------------------
def load_peer_names():
    names = {}
    if not WG_CONF_PATH.exists():
        return names

    content = WG_CONF_PATH.read_text(errors="ignore")
    blocks = re.split(r"\n(?=\[Peer\])", content)
    for block in blocks:
        if "[Peer]" not in block:
            continue
        name_match = re.search(r"#\s*Client\s*:\s*(.+)", block)
        key_match = re.search(r"PublicKey\s*=\s*(\S+)", block)
        if name_match and key_match:
            names[key_match.group(1)] = name_match.group(1).strip()
    return names


# ------------------------------------------------------------------
# Etat en direct via `wg show <if> dump`
# ------------------------------------------------------------------
def load_live_peers():
    names = load_peer_names()
    peers = []
    try:
        raw = subprocess.check_output(
            ["wg", "show", WG_INTERFACE, "dump"], text=True, stderr=subprocess.DEVNULL
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return peers

    lines = raw.strip().splitlines()
    now = int(datetime.now(tz=timezone.utc).timestamp())

    for line in lines[1:]:  # la 1ere ligne decrit l'interface elle-meme
        parts = line.split("\t")
        if len(parts) < 8:
            continue
        pubkey, _psk, endpoint, allowed_ips, handshake, rx, tx, _keepalive = parts[:8]
        handshake_ts = int(handshake) if handshake.isdigit() else 0
        seconds_since = (now - handshake_ts) if handshake_ts else None
        status = (
            "online"
            if seconds_since is not None and seconds_since < HANDSHAKE_ONLINE_THRESHOLD_SEC
            else ("idle" if handshake_ts else "never")
        )
        peers.append(
            {
                "name": names.get(pubkey, pubkey[:8] + "…"),
                "public_key": pubkey,
                "endpoint": endpoint if endpoint != "(none)" else None,
                "allowed_ips": allowed_ips,
                "last_handshake": (
                    datetime.fromtimestamp(handshake_ts, tz=timezone.utc).isoformat()
                    if handshake_ts
                    else None
                ),
                "seconds_since_handshake": seconds_since,
                "rx_bytes": int(rx) if rx.isdigit() else 0,
                "tx_bytes": int(tx) if tx.isdigit() else 0,
                "status": status,
            }
        )
    return sorted(peers, key=lambda p: p["name"].lower())


# ------------------------------------------------------------------
# Journal des connexions (fichier CSV genere par 04-logging-monitoring.sh)
# ------------------------------------------------------------------
def load_logs(limit=200):
    names = load_peer_names()
    rows = []
    if not LOG_CSV_PATH.exists():
        return rows

    with LOG_CSV_PATH.open(newline="", errors="ignore") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pubkey = row.get("peer_public_key", "")
            rows.append(
                {
                    "timestamp": row.get("timestamp"),
                    "peer": names.get(pubkey, (pubkey[:8] + "…") if pubkey else "?"),
                    "public_key": pubkey,
                    "endpoint": row.get("endpoint"),
                    "allowed_ips": row.get("allowed_ips"),
                    "last_handshake": row.get("last_handshake"),
                    "rx_bytes": int(row.get("rx_bytes") or 0),
                    "tx_bytes": int(row.get("tx_bytes") or 0),
                }
            )
    return rows[-limit:][::-1]


def build_throughput_series(logs, buckets=12):
    """Agrège rx/tx par horodatage (les captures cron sont déjà à 5 min)."""
    series = {}
    for row in logs:
        ts = row["timestamp"]
        if not ts:
            continue
        bucket = ts[:16]  # YYYY-MM-DD HH:MM
        entry = series.setdefault(bucket, {"t": bucket[-5:], "rx": 0, "tx": 0})
        entry["rx"] += row["rx_bytes"]
        entry["tx"] += row["tx_bytes"]
    ordered = [series[k] for k in sorted(series.keys())]
    return ordered[-buckets:]


# ------------------------------------------------------------------
# Routes API
# ------------------------------------------------------------------
@app.get("/healthz")
def healthz():
    return jsonify({"status": "ok"})


@app.get("/api/peers")
def api_peers():
    return jsonify(load_live_peers())


@app.get("/api/logs")
def api_logs():
    limit = int(request.args.get("limit", 200))
    return jsonify(load_logs(limit=limit))


@app.get("/api/overview")
def api_overview():
    peers = load_live_peers()
    logs = load_logs(limit=300)

    active = sum(1 for p in peers if p["status"] == "online")
    total_rx = sum(p["rx_bytes"] for p in peers)
    total_tx = sum(p["tx_bytes"] for p in peers)

    return jsonify(
        {
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "stats": {
                "active_tunnels": active,
                "total_peers": len(peers),
                "total_rx_bytes": total_rx,
                "total_tx_bytes": total_tx,
                "alerts": sum(1 for p in peers if p["status"] == "never"),
            },
            "peers": peers,
            "logs": logs[:100],
            "throughput_series": build_throughput_series(logs),
        }
    )


# ------------------------------------------------------------------
# Frontend statique (index.html, css, js)
# ------------------------------------------------------------------
@app.get("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
