#!/usr/bin/env python3
"""
BLOCKHash - wgstate.py
=========================================================
Logique de lecture partagee entre le service web (app.py, sous
gunicorn/www-data, dans le venv du dashboard) et les scripts cron
independants (alerts.py, qui tourne en root via systemd/cron et n'a
PAS besoin de Flask). Aucune dependance externe ici : uniquement la
bibliotheque standard, pour que ce module reste utilisable avec le
python3 systeme comme avec celui du venv.

Ne fait AUCUNE ecriture : uniquement de la lecture (wg0.conf, `wg show
... dump`, tunnels.csv). Pour toute ecriture (ajout/suppression/
modification de client), voir wgctl.py.
"""

import csv
import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

WG_INTERFACE = os.environ.get("WG_INTERFACE", "wg0")
WG_CONF_PATH = Path(os.environ.get("WG_CONF_PATH", "/etc/wireguard/wg0.conf"))
LOG_CSV_PATH = Path(os.environ.get("WG_LOG_CSV", "/var/log/wireguard/tunnels.csv"))


# ------------------------------------------------------------------
# Extraction des infos clients depuis wg0.conf
# (wgctl.py insere "# Client : nom" + "# Meta : {...}" juste avant
#  chaque bloc [Peer] ; un client desactive a chaque ligne de son
#  bloc prefixee d'un "#" supplementaire, voir wgctl.py pour le detail)
# ------------------------------------------------------------------
def load_peer_config():
    """Lit TOUS les blocs [Peer] (actifs et desactives) et renvoie un dict
    pubkey -> {name, allowed_ips, enabled, created, expires, bw_up_mbit, bw_down_mbit}."""
    peers = {}
    if not WG_CONF_PATH.exists():
        return peers

    try:
    import subprocess
    content = subprocess.check_output(["sudo", "cat", str(WG_CONF_PATH)], stderr=subprocess.DEVNULL, text=True)
except subprocess.CalledProcessError:
    content = ""
    lines = content.splitlines()
    starts = [i for i, ln in enumerate(lines) if re.match(r"^#{0,2}\[Peer\]\s*$", ln)]

    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
        raw_block = lines[start:end]
        disabled = raw_block[0].startswith("#")
        canon = [ln[1:] if (disabled and ln.startswith("#")) else ln for ln in raw_block]
        canon_text = "\n".join(canon)

        pub_m = re.search(r"^PublicKey\s*=\s*(\S+)", canon_text, re.MULTILINE)
        if not pub_m:
            continue
        name_m = re.search(r"^#\s*Client\s*:\s*(.+)$", canon_text, re.MULTILINE)
        meta_m = re.search(r"^#\s*Meta\s*:\s*(\{.*\})\s*$", canon_text, re.MULTILINE)
        aips_m = re.search(r"^AllowedIPs\s*=\s*(\S+)", canon_text, re.MULTILINE)

        try:
            meta = json.loads(meta_m.group(1)) if meta_m else {}
        except json.JSONDecodeError:
            meta = {}

        pubkey = pub_m.group(1)
        peers[pubkey] = {
            "name": name_m.group(1).strip() if name_m else pubkey[:8] + "…",
            "allowed_ips": aips_m.group(1) if aips_m else None,
            "enabled": not disabled,
            "created": meta.get("created"),
            "expires": meta.get("expires"),
            "bw_up_mbit": meta.get("bw_up_mbit"),
            "bw_down_mbit": meta.get("bw_down_mbit"),
        }
    return peers


def load_peer_names():
    """pubkey -> nom, pour les pairs actifs uniquement (compatibilite `wg show`)."""
    return {pk: info["name"] for pk, info in load_peer_config().items() if info["enabled"]}


# ------------------------------------------------------------------
# Etat en direct via `wg show <if> dump`, fusionne avec la config
# complete (y compris les clients desactives, absents de `wg show`)
# ------------------------------------------------------------------
def load_live_peers(online_threshold_sec=180):
    config = load_peer_config()
    now = int(datetime.now(tz=timezone.utc).timestamp())

    live_by_key = {}
    try:
        raw = subprocess.check_output(
            ["wg", "show", WG_INTERFACE, "dump"], text=True, stderr=subprocess.DEVNULL
        )
        for line in raw.strip().splitlines()[1:]:  # la 1ere ligne decrit l'interface elle-meme
            parts = line.split("\t")
            if len(parts) < 8:
                continue
            pubkey, _psk, endpoint, allowed_ips, handshake, rx, tx, _keepalive = parts[:8]
            live_by_key[pubkey] = {
                "endpoint": endpoint if endpoint != "(none)" else None,
                "allowed_ips": allowed_ips,
                "handshake_ts": int(handshake) if handshake.isdigit() else 0,
                "rx_bytes": int(rx) if rx.isdigit() else 0,
                "tx_bytes": int(tx) if tx.isdigit() else 0,
            }
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass  # `wg show` indisponible -> on retombe sur la config seule

    peers = []
    all_keys = set(config.keys()) | set(live_by_key.keys())
    for pubkey in all_keys:
        cfg = config.get(pubkey, {})
        live = live_by_key.get(pubkey)
        enabled = cfg.get("enabled", True)

        handshake_ts = live["handshake_ts"] if live else 0
        seconds_since = (now - handshake_ts) if handshake_ts else None
        if not enabled:
            status = "disabled"
        elif seconds_since is not None and seconds_since < online_threshold_sec:
            status = "online"
        elif handshake_ts:
            status = "idle"
        else:
            status = "never"

        peers.append(
            {
                "name": cfg.get("name", pubkey[:8] + "…"),
                "public_key": pubkey,
                "endpoint": live["endpoint"] if live else None,
                "allowed_ips": (live["allowed_ips"] if live else cfg.get("allowed_ips")) or "—",
                "last_handshake": (
                    datetime.fromtimestamp(handshake_ts, tz=timezone.utc).isoformat()
                    if handshake_ts
                    else None
                ),
                "seconds_since_handshake": seconds_since,
                "rx_bytes": live["rx_bytes"] if live else 0,
                "tx_bytes": live["tx_bytes"] if live else 0,
                "status": status,
                "enabled": enabled,
                "created": cfg.get("created"),
                "expires": cfg.get("expires"),
                "bw_up_mbit": cfg.get("bw_up_mbit"),
                "bw_down_mbit": cfg.get("bw_down_mbit"),
            }
        )
    return sorted(peers, key=lambda p: p["name"].lower())


# ------------------------------------------------------------------
# Journal des connexions (SQLite via store.py, voir README 7.10.1 -
# remplace la lecture CSV pour eviter de recharger tout le fichier a
# chaque requete ; le CSV reste ecrit en parallele comme trace texte
# brute, mais n'est plus lu par le dashboard)
# ------------------------------------------------------------------
def _row_to_log_dict(row, names):
    pubkey = row["pubkey"]
    ts_str = datetime.fromtimestamp(row["ts"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    handshake = row["last_handshake"]
    return {
        "timestamp": ts_str,
        "ts": row["ts"],
        "peer": names.get(pubkey, (pubkey[:8] + "…") if pubkey else "?"),
        "public_key": pubkey,
        "endpoint": row["endpoint"],
        "allowed_ips": row["allowed_ips"],
        "last_handshake": (
            datetime.fromtimestamp(handshake, tz=timezone.utc).isoformat() if handshake else None
        ),
        "rx_bytes": row["rx_bytes"],
        "tx_bytes": row["tx_bytes"],
    }


def load_logs(limit=200, offset=0, search=None, pubkey=None, pubkeys=None, sort_key="ts", sort_dir="desc"):
    """Renvoie {"total": N, "rows": [...]}, pagine au niveau SQL (voir
    store.query_logs) - contrairement a l'ancienne version CSV, ne charge
    jamais plus de `limit` lignes en memoire."""
    import store  # import différé : évite un cycle si store.py évolue un jour pour importer wgstate

    names = load_peer_names()
    result = store.query_logs(
        limit=limit, offset=offset, pubkey=pubkey, pubkeys=pubkeys, search=search, sort_key=sort_key, sort_dir=sort_dir
    )
    return {"total": result["total"], "rows": [_row_to_log_dict(r, names) for r in result["rows"]]}


def build_reconnect_stats(rows):
    """Approxime le nombre de reconnexions et la derniere IP endpoint vue :
    une nouvelle "session" commence quand l'ecart entre deux captures
    consecutives depasse 2x l'intervalle de capture habituel (5 min ->
    seuil 10 min), ou quand l'endpoint change. C'est une heuristique (le
    journal est echantillonne toutes les 5 min, pas evenementiel).
    `rows` : liste de dicts avec au moins "ts" (int, secondes) et "endpoint",
    triee ou non (triee ici par securite)."""
    if not rows:
        return {"reconnect_count": 0, "last_endpoint": None}

    ordered = sorted(rows, key=lambda r: r["ts"])
    sessions = 1
    prev = ordered[0]
    for row in ordered[1:]:
        gap_new_session = (row["ts"] - prev["ts"]) > 600
        if gap_new_session or (row["endpoint"] and row["endpoint"] != prev["endpoint"]):
            sessions += 1
        prev = row

    return {
        "reconnect_count": max(0, sessions - 1),
        "last_endpoint": ordered[-1]["endpoint"],
    }


def reconnect_counts_last_24h():
    """pubkey -> nombre de reconnexions estimees sur les dernieres 24h
    (utilise par anomalies.py pour detecter un endpoint qui change trop souvent)."""
    import store

    cutoff_ts = int((datetime.now(tz=timezone.utc) - timedelta(hours=24)).timestamp())
    counts = {}
    for pubkey in load_peer_config():
        rows = [r for r in store.query_logs_for_pubkey(pubkey) if r["ts"] >= cutoff_ts]
        counts[pubkey] = build_reconnect_stats(rows)["reconnect_count"]
    return counts


def build_throughput_series(logs, buckets=12):
    """Agrège rx/tx par horodatage (les captures cron sont déjà à 5 min).
    NB : ces valeurs sont les compteurs CUMULATIFS bruts sommes par bucket,
    pas un delta (limite heritee du CSV) - pour un debit correct sur une
    plage choisie, voir store.query_series() qui calcule de vrais deltas
    depuis la base SQLite dediee."""
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
