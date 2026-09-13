#!/usr/bin/env python3
"""
BLOCKHash - store.py
=========================================================
Petite base SQLite partagee pour :
  1) l'historique long terme du debit (table `samples`), alimentee par
     un hook ajoute a scripts/04-logging-monitoring.sh (meme cadence
     5 min que le journal CSV existant, meme source `wg show wg0 dump`) ;
  2) l'historique des alertes envoyees et leur deduplication (table
     `alerts` / `alert_state`), alimentee par alerts.py.

Pourquoi SQLite plutot que le CSV existant pour le long terme ? Le CSV
(`tunnels.csv`) est deja utilise pour le journal brut et l'heuristique
de reconnexion (voir app.py) ; le relire integralement pour chaque
requete de graphique sur 30 jours (8 700+ lignes/pair) serait couteux
et fragile. Le compteur `rx_bytes`/`tx_bytes` de `wg show` est de plus
CUMULATIF depuis le demarrage de l'interface, pas un delta : ce module
stocke les valeurs brutes puis calcule les deltas entre echantillons
consecutifs au moment de la requete, pour obtenir un vrai débit par
intervalle (voir `query_series`).

Ce fichier est volontairement independant de app.py (pas d'import
Flask) pour pouvoir etre appele en ligne de commande depuis le cron
d'ingestion, qui tourne en root, separement du service web (www-data).
"""

import argparse
import json
import os
import re
import sqlite3
import statistics
import sys
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path(os.environ.get("METRICS_DB_PATH", "/var/log/wireguard/blockhash.db"))
DB_GROUP = os.environ.get("METRICS_DB_GROUP", "www-data")  # groupe autorise a LIRE la base
RETENTION_DAYS = int(os.environ.get("METRICS_RETENTION_DAYS", "35"))

# Plage -> (fenetre en secondes, taille de bucket en secondes)
RANGE_CONFIG = {
    "1h": (3600, 60),
    "24h": (86400, 900),
    "7j": (7 * 86400, 3600),
    "30j": (30 * 86400, 21600),
}


def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")  # lecteurs (Flask) non bloques par l'ecrivain (cron)
    return conn


def init_db():
    with closing(get_conn()) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                pubkey TEXT NOT NULL,
                endpoint TEXT,
                rx_bytes INTEGER NOT NULL,
                tx_bytes INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_samples_pubkey_ts ON samples(pubkey, ts);

            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                level TEXT NOT NULL,
                source TEXT NOT NULL,
                message TEXT NOT NULL,
                channels TEXT,
                rule_key TEXT,
                peer_name TEXT,
                read_at INTEGER,
                archived INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_alerts_ts ON alerts(ts);

            CREATE TABLE IF NOT EXISTS alert_state (
                rule_key TEXT PRIMARY KEY,
                last_sent_ts INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS peer_last_ip (
                pubkey TEXT PRIMARY KEY,
                endpoint_ip TEXT,
                country TEXT,
                updated_ts INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                pubkey TEXT NOT NULL,
                endpoint TEXT,
                allowed_ips TEXT,
                last_handshake INTEGER,
                rx_bytes INTEGER NOT NULL,
                tx_bytes INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_logs_ts ON logs(ts);
            CREATE INDEX IF NOT EXISTS idx_logs_pubkey_ts ON logs(pubkey, ts);

            CREATE TABLE IF NOT EXISTS geoip_cache (
                ip TEXT PRIMARY KEY,
                lat REAL,
                lon REAL,
                city TEXT,
                country TEXT,
                cached_ts INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS push_subscriptions (
                endpoint TEXT PRIMARY KEY,
                p256dh TEXT NOT NULL,
                auth TEXT NOT NULL,
                created_ts INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_ts INTEGER NOT NULL,
                last_login_ts INTEGER
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                created_ts INTEGER NOT NULL,
                expires_ts INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS api_tokens (
                token_hash TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                scope TEXT NOT NULL,
                created_by TEXT,
                created_ts INTEGER NOT NULL,
                expires_ts INTEGER,
                last_used_ts INTEGER,
                revoked INTEGER NOT NULL DEFAULT 0
            );
            """
        )
        conn.commit()
        # Migration idempotente : ajoute les colonnes manquantes si la base
        # existait deja (deploiement anterieur a l'introduction de ces
        # champs) - ALTER TABLE ... ADD COLUMN echoue si la colonne existe
        # deja, ce qui est attendu et simplement ignore.
        for column_def in (
            "rule_key TEXT", "peer_name TEXT", "read_at INTEGER", "archived INTEGER NOT NULL DEFAULT 0",
        ):
            try:
                conn.execute(f"ALTER TABLE alerts ADD COLUMN {column_def}")
                conn.commit()
            except sqlite3.OperationalError:
                pass  # colonne deja presente
    _fix_permissions()


def _fix_permissions():
    """La base est ecrite par root (cron) mais lue par www-data (Flask) :
    on l'ouvre en lecture au groupe de service apres chaque ecriture."""
    try:
        import grp

        gid = grp.getgrnam(DB_GROUP).gr_gid
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(DB_PATH) + suffix)
            if p.exists():
                os.chown(p, 0, gid)  # conserve owner root, ajuste seulement le groupe
                os.chmod(p, 0o640)
    except (KeyError, PermissionError, ImportError):
        pass  # best effort (ex: execute par un non-root pendant les tests)


# ---------------------------------------------------------------------
# Ingestion (appelee toutes les 5 min par le cron de logging, en root)
# ---------------------------------------------------------------------
def ingest_wg_dump(ts, dump_text):
    """dump_text : sortie brute de `wg show <if> dump`, EN-TETE INCLUS OU NON
    (les deux formes sont acceptees ; une ligne d'en-tete a moins de 8 colonnes
    et est simplement ignoree)."""
    init_db()
    rows = []
    for line in dump_text.strip().splitlines():
        parts = line.split("\t")
        if len(parts) < 8:
            continue
        pubkey, _psk, endpoint, _allowed_ips, _handshake, rx, tx, _keepalive = parts[:8]
        if not re.match(r"^[A-Za-z0-9+/=]{20,}$", pubkey):
            continue  # ligne d'entete ou ligne malformee
        rows.append(
            (
                ts,
                pubkey,
                endpoint if endpoint != "(none)" else None,
                int(rx) if rx.isdigit() else 0,
                int(tx) if tx.isdigit() else 0,
            )
        )

    if not rows:
        return 0

    with closing(get_conn()) as conn:
        conn.executemany(
            "INSERT INTO samples (ts, pubkey, endpoint, rx_bytes, tx_bytes) VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    _fix_permissions()
    return len(rows)


def prune_old(retention_days=RETENTION_DAYS):
    cutoff = int((datetime.now(tz=timezone.utc) - timedelta(days=retention_days)).timestamp())
    with closing(get_conn()) as conn:
        conn.execute("DELETE FROM samples WHERE ts < ?", (cutoff,))
        conn.execute("DELETE FROM alerts WHERE ts < ?", (cutoff,))
        conn.execute("DELETE FROM logs WHERE ts < ?", (cutoff,))
        conn.commit()
        conn.execute("VACUUM")
    _fix_permissions()


# ---------------------------------------------------------------------
# Journal des connexions (remplace le CSV comme source interrogeable ;
# le CSV reste ecrit en parallele par 04-logging-monitoring.sh comme
# trace texte brute lisible sans outillage - voir README 7.10.1)
# ---------------------------------------------------------------------
def ingest_log_snapshot(ts, dump_text):
    """Meme source (`wg show <if> dump`) et meme cadence que ingest_wg_dump,
    mais stocke une ligne PAR CAPTURE (pas de delta ici : le journal affiche
    volontairement les compteurs cumulatifs bruts au moment de la capture,
    comme le faisait le CSV) - une ligne par pair, a chaque cycle de 5 min."""
    init_db()
    rows = []
    for line in dump_text.strip().splitlines():
        parts = line.split("\t")
        if len(parts) < 8:
            continue
        pubkey, _psk, endpoint, allowed_ips, handshake, rx, tx, _keepalive = parts[:8]
        if not re.match(r"^[A-Za-z0-9+/=]{20,}$", pubkey):
            continue
        rows.append(
            (
                ts,
                pubkey,
                endpoint if endpoint != "(none)" else None,
                allowed_ips,
                int(handshake) if handshake.isdigit() else None,
                int(rx) if rx.isdigit() else 0,
                int(tx) if tx.isdigit() else 0,
            )
        )
    if not rows:
        return 0
    with closing(get_conn()) as conn:
        conn.executemany(
            "INSERT INTO logs (ts, pubkey, endpoint, allowed_ips, last_handshake, rx_bytes, tx_bytes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    _fix_permissions()
    return len(rows)


def query_logs(limit=50, offset=0, pubkey=None, pubkeys=None, search=None, sort_key="ts", sort_dir="desc",
               ts_from=None, ts_to=None, volume_min=None, volume_max=None):
    """Pagination REELLE au niveau SQL (LIMIT/OFFSET), contrairement a
    l'ancienne implementation CSV qui chargeait tout le fichier en memoire
    a chaque requete. `search` filtre sur l'endpoint ou la cle publique
    (le nom du client est resolu cote appelant, apres la requete, a partir
    de wg0.conf - voir wgstate.load_logs). `pubkeys` (liste) permet de
    combiner la pagination avec un filtre de statut calcule cote appelant
    (ex: tous les pairs actuellement "en ligne") sans casser la pagination.
    `ts_from`/`ts_to` (epoch sec) et `volume_min`/`volume_max` (octets,
    somme rx+tx) filtrent respectivement par plage de dates et par volume."""
    init_db()
    sort_col = {
        "ts": "ts",
        "timestamp": "ts",
        "rx_bytes": "rx_bytes",
        "tx_bytes": "tx_bytes",
        "endpoint": "endpoint",
        "allowed_ips": "allowed_ips",
    }.get(sort_key, "ts")
    sort_dir = "ASC" if str(sort_dir).lower() == "asc" else "DESC"

    where = []
    params = []
    if pubkey:
        where.append("pubkey = ?")
        params.append(pubkey)
    if pubkeys is not None:
        if not pubkeys:
            return {"total": 0, "rows": []}  # liste vide -> aucun resultat possible, evite un IN () invalide
        where.append(f"pubkey IN ({','.join('?' * len(pubkeys))})")
        params += list(pubkeys)
    if search:
        where.append("(endpoint LIKE ? OR pubkey LIKE ? OR allowed_ips LIKE ?)")
        like = f"%{search}%"
        params += [like, like, like]
    if ts_from is not None:
        where.append("ts >= ?"); params.append(ts_from)
    if ts_to is not None:
        where.append("ts <= ?"); params.append(ts_to)
    if volume_min is not None:
        where.append("(rx_bytes + tx_bytes) >= ?"); params.append(volume_min)
    if volume_max is not None:
        where.append("(rx_bytes + tx_bytes) <= ?"); params.append(volume_max)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    with closing(get_conn()) as conn:
        conn.row_factory = sqlite3.Row
        total = conn.execute(f"SELECT COUNT(*) FROM logs {where_sql}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM logs {where_sql} ORDER BY {sort_col} {sort_dir} LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()

    return {"total": total, "rows": [dict(r) for r in rows]}


def query_logs_for_pubkey(pubkey, limit=100000):
    """Toutes les lignes d'un pair, triees chronologiquement (utilise par
    build_reconnect_stats / le tiroir d'historique client, voir wgstate.py)."""
    result = query_logs(limit=limit, offset=0, pubkey=pubkey, sort_key="ts", sort_dir="asc")
    return result["rows"]


# ---------------------------------------------------------------------
# Cache GeoIP (voir geoip.py) - evite de re-interroger l'API externe a
# chaque affichage de la carte, et respecte sa limite de requetes/minute.
# ---------------------------------------------------------------------
def geoip_cache_get(ip):
    init_db()
    with closing(get_conn()) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM geoip_cache WHERE ip = ?", (ip,)).fetchone()
        return dict(row) if row else None


def geoip_cache_set(ip, lat, lon, city, country, now=None):
    init_db()
    now = now if now is not None else int(datetime.now(tz=timezone.utc).timestamp())
    with closing(get_conn()) as conn:
        conn.execute(
            "INSERT INTO geoip_cache (ip, lat, lon, city, country, cached_ts) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(ip) DO UPDATE SET lat=excluded.lat, lon=excluded.lon, city=excluded.city, "
            "country=excluded.country, cached_ts=excluded.cached_ts",
            (ip, lat, lon, city, country, now),
        )
        conn.commit()
    _fix_permissions()


# ---------------------------------------------------------------------
# Lecture : serie de debit avec deltas corrects + bucketing par plage
# ---------------------------------------------------------------------
def query_series(pubkey, range_key, now=None):
    """Renvoie une liste de {"t": libelle, "rx": octets/intervalle, "tx": ...}
    pour la plage demandee. `pubkey=None` agrège tous les pairs connus.
    Le premier echantillon de chaque pair a l'interieur de la fenetre sert
    uniquement de reference (son delta n'est pas exploitable sans un point
    precedent) -> on recupere un echantillon supplementaire juste avant le
    debut de la fenetre pour ne pas perdre le premier intervalle."""
    if range_key not in RANGE_CONFIG:
        raise ValueError(f"Plage inconnue : {range_key} (attendu : {', '.join(RANGE_CONFIG)})")
    init_db()  # base pas encore initialisee (dashboard fraichement installe, cron pas encore passe)
    window_sec, bucket_sec = RANGE_CONFIG[range_key]
    now_ts = now if now is not None else int(datetime.now(tz=timezone.utc).timestamp())
    start_ts = now_ts - window_sec

    with closing(get_conn()) as conn:
        conn.row_factory = sqlite3.Row
        if pubkey:
            cur = conn.execute(
                """
                SELECT ts, pubkey, rx_bytes, tx_bytes FROM samples
                WHERE pubkey = ? AND ts >= (
                    SELECT COALESCE(MAX(ts), 0) FROM samples WHERE pubkey = ? AND ts < ?
                )
                ORDER BY ts ASC
                """,
                (pubkey, pubkey, start_ts),
            )
        else:
            cur = conn.execute(
                """
                SELECT ts, pubkey, rx_bytes, tx_bytes FROM samples
                WHERE ts >= ? - ?
                ORDER BY pubkey ASC, ts ASC
                """,
                (start_ts, bucket_sec * 3),  # marge raisonnable pour retrouver un point "avant" par pair
            )
        rows = cur.fetchall()

    # Deltas par pair (les compteurs `wg` sont cumulatifs depuis le demarrage
    # de l'interface ; un delta negatif = redemarrage/rotation -> ignore comme 0)
    buckets = {}
    last_by_pubkey = {}
    for row in rows:
        key = row["pubkey"]
        prev = last_by_pubkey.get(key)
        last_by_pubkey[key] = row
        if prev is None or row["ts"] < start_ts:
            continue  # sert seulement de reference pour le prochain delta
        drx = max(0, row["rx_bytes"] - prev["rx_bytes"])
        dtx = max(0, row["tx_bytes"] - prev["tx_bytes"])
        bucket_ts = row["ts"] - (row["ts"] % bucket_sec)
        entry = buckets.setdefault(bucket_ts, {"rx": 0, "tx": 0})
        entry["rx"] += drx
        entry["tx"] += dtx

    fmt = "%H:%M" if window_sec <= 86400 else "%d/%m"
    series = [
        {
            "t": datetime.fromtimestamp(bucket_ts, tz=timezone.utc).strftime(fmt),
            "ts": bucket_ts,
            "rx": v["rx"],
            "tx": v["tx"],
        }
        for bucket_ts, v in sorted(buckets.items())
    ]
    return series


def latest_bucket_totals(pubkey=None, bucket_sec=300, now=None):
    """Debit (delta) sur le dernier intervalle uniquement, pour l'evaluation
    des regles d'alerte de type 'seuil de bande passante'."""
    series = query_series(pubkey, "1h", now=now)
    return series[-1] if series else {"rx": 0, "tx": 0}


# ---------------------------------------------------------------------
# Anomalies simples (pic de trafic) — reutilise par anomalies.py
# ---------------------------------------------------------------------
def detect_traffic_spike(pubkey, range_key="24h", z_threshold=3.0, min_floor_bytes=1_000_000):
    series = query_series(pubkey, range_key)
    if len(series) < 6:
        return None
    values = [b["rx"] + b["tx"] for b in series]
    *history, last = values
    mean = statistics.mean(history)
    stdev = statistics.pstdev(history) if len(history) > 1 else 0
    if last <= max(mean + z_threshold * stdev, min_floor_bytes):
        return None
    return {"mean": mean, "stdev": stdev, "last": last, "bucket": series[-1]["t"]}


# ---------------------------------------------------------------------
# Alertes : historique + deduplication
# ---------------------------------------------------------------------
def insert_alert(level, source, message, channels=None, ts=None, rule_key=None, peer_name=None):
    init_db()
    ts = ts if ts is not None else int(datetime.now(tz=timezone.utc).timestamp())
    with closing(get_conn()) as conn:
        conn.execute(
            "INSERT INTO alerts (ts, level, source, message, channels, rule_key, peer_name) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ts, level, source, message, json.dumps(channels or []), rule_key, peer_name),
        )
        conn.commit()
    _fix_permissions()


def list_alerts(limit=50, offset=0, severity=None, peer_name=None, rule=None, ts_from=None, ts_to=None, archived=None):
    init_db()
    clauses, params = [], []
    if severity:
        clauses.append("level = ?"); params.append(severity)
    if peer_name:
        clauses.append("peer_name LIKE ?"); params.append(f"%{peer_name}%")
    if rule:
        clauses.append("rule_key LIKE ?"); params.append(f"{rule}%")
    if ts_from is not None:
        clauses.append("ts >= ?"); params.append(ts_from)
    if ts_to is not None:
        clauses.append("ts <= ?"); params.append(ts_to)
    if archived is not None:
        clauses.append("archived = ?"); params.append(1 if archived else 0)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    with closing(get_conn()) as conn:
        conn.row_factory = sqlite3.Row
        total = conn.execute(f"SELECT COUNT(*) FROM alerts {where}", params).fetchone()[0]
        cur = conn.execute(
            f"SELECT * FROM alerts {where} ORDER BY ts DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        )
        return {"rows": [dict(r) for r in cur.fetchall()], "total": total}


def mark_alert_read(alert_id):
    init_db()
    with closing(get_conn()) as conn:
        conn.execute("UPDATE alerts SET read_at = ? WHERE id = ?", (int(datetime.now(tz=timezone.utc).timestamp()), alert_id))
        conn.commit()


def set_alert_archived(alert_id, archived=True):
    init_db()
    with closing(get_conn()) as conn:
        conn.execute("UPDATE alerts SET archived = ? WHERE id = ?", (1 if archived else 0, alert_id))
        conn.commit()


def delete_alert(alert_id):
    init_db()
    with closing(get_conn()) as conn:
        conn.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))
        conn.commit()


def count_alerts_last_hour():
    init_db()
    since = int(datetime.now(tz=timezone.utc).timestamp()) - 3600
    with closing(get_conn()) as conn:
        return conn.execute("SELECT COUNT(*) FROM alerts WHERE ts >= ?", (since,)).fetchone()[0]


def alerts_stats(days=7):
    """Agrégats pour le tableau de bord des alertes : volume par jour et par
    sévérité, top 5 des clients les plus alertés, et un MTTA approximatif
    (delai moyen entre creation et premiere lecture, sur les alertes lues)."""
    init_db()
    since = int(datetime.now(tz=timezone.utc).timestamp()) - days * 86400
    with closing(get_conn()) as conn:
        conn.row_factory = sqlite3.Row
        by_day = conn.execute(
            "SELECT date(ts, 'unixepoch') AS day, level, COUNT(*) AS n FROM alerts "
            "WHERE ts >= ? GROUP BY day, level ORDER BY day",
            (since,),
        ).fetchall()
        top_clients = conn.execute(
            "SELECT peer_name, COUNT(*) AS n FROM alerts WHERE ts >= ? AND peer_name IS NOT NULL "
            "GROUP BY peer_name ORDER BY n DESC LIMIT 5",
            (since,),
        ).fetchall()
        mtta_row = conn.execute(
            "SELECT AVG(read_at - ts) AS avg_sec FROM alerts WHERE ts >= ? AND read_at IS NOT NULL",
            (since,),
        ).fetchone()
    return {
        "by_day": [dict(r) for r in by_day],
        "top_clients": [dict(r) for r in top_clients],
        "mtta_seconds": mtta_row["avg_sec"] if mtta_row and mtta_row["avg_sec"] is not None else None,
    }


def save_push_subscription(endpoint, p256dh, auth):
    init_db()
    with closing(get_conn()) as conn:
        conn.execute(
            "INSERT INTO push_subscriptions (endpoint, p256dh, auth, created_ts) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(endpoint) DO UPDATE SET p256dh = excluded.p256dh, auth = excluded.auth",
            (endpoint, p256dh, auth, int(datetime.now(tz=timezone.utc).timestamp())),
        )
        conn.commit()


def delete_push_subscription(endpoint):
    init_db()
    with closing(get_conn()) as conn:
        conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
        conn.commit()


def list_push_subscriptions():
    init_db()
    with closing(get_conn()) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute("SELECT * FROM push_subscriptions").fetchall()]


# ------------------------------------------------------------------
# Comptes utilisateurs, sessions de connexion, tokens API (items 49/52)
# ------------------------------------------------------------------
def create_user(username, password_hash, role, ts=None):
    init_db()
    ts = ts if ts is not None else int(datetime.now(tz=timezone.utc).timestamp())
    with closing(get_conn()) as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash, role, active, created_ts) VALUES (?, ?, ?, 1, ?)",
            (username, password_hash, role, ts),
        )
        conn.commit()


def get_user(username):
    init_db()
    with closing(get_conn()) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return dict(row) if row else None


def list_users():
    init_db()
    with closing(get_conn()) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT username, role, active, created_ts, last_login_ts FROM users ORDER BY created_ts")
        return [dict(r) for r in cur.fetchall()]


def count_active_admins(exclude_username=None):
    init_db()
    with closing(get_conn()) as conn:
        if exclude_username:
            return conn.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'admin' AND active = 1 AND username != ?", (exclude_username,)
            ).fetchone()[0]
        return conn.execute("SELECT COUNT(*) FROM users WHERE role = 'admin' AND active = 1").fetchone()[0]


def update_user(username, role=None, active=None, password_hash=None):
    init_db()
    sets, params = [], []
    if role is not None:
        sets.append("role = ?"); params.append(role)
    if active is not None:
        sets.append("active = ?"); params.append(1 if active else 0)
    if password_hash is not None:
        sets.append("password_hash = ?"); params.append(password_hash)
    if not sets:
        return
    params.append(username)
    with closing(get_conn()) as conn:
        conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE username = ?", params)
        conn.commit()


def touch_user_login(username, ts=None):
    init_db()
    ts = ts if ts is not None else int(datetime.now(tz=timezone.utc).timestamp())
    with closing(get_conn()) as conn:
        conn.execute("UPDATE users SET last_login_ts = ? WHERE username = ?", (ts, username))
        conn.commit()


def delete_user(username):
    init_db()
    with closing(get_conn()) as conn:
        conn.execute("DELETE FROM users WHERE username = ?", (username,))
        conn.execute("DELETE FROM sessions WHERE username = ?", (username,))
        conn.commit()


def create_session(token_hash, username, ttl_seconds, ts=None):
    init_db()
    ts = ts if ts is not None else int(datetime.now(tz=timezone.utc).timestamp())
    with closing(get_conn()) as conn:
        conn.execute(
            "INSERT INTO sessions (token_hash, username, created_ts, expires_ts) VALUES (?, ?, ?, ?)",
            (token_hash, username, ts, ts + ttl_seconds),
        )
        conn.commit()


def get_session(token_hash):
    init_db()
    now = int(datetime.now(tz=timezone.utc).timestamp())
    with closing(get_conn()) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM sessions WHERE token_hash = ? AND expires_ts > ?", (token_hash, now)
        ).fetchone()
        return dict(row) if row else None


def delete_sessions_for_user(username):
    init_db()
    with closing(get_conn()) as conn:
        conn.execute("DELETE FROM sessions WHERE username = ?", (username,))
        conn.commit()


def create_api_token(token_hash, name, scope, created_by, expires_ts=None, ts=None):
    init_db()
    ts = ts if ts is not None else int(datetime.now(tz=timezone.utc).timestamp())
    with closing(get_conn()) as conn:
        conn.execute(
            "INSERT INTO api_tokens (token_hash, name, scope, created_by, created_ts, expires_ts) VALUES (?, ?, ?, ?, ?, ?)",
            (token_hash, name, scope, created_by, ts, expires_ts),
        )
        conn.commit()


def get_api_token(token_hash):
    init_db()
    now = int(datetime.now(tz=timezone.utc).timestamp())
    with closing(get_conn()) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM api_tokens WHERE token_hash = ? AND revoked = 0 AND (expires_ts IS NULL OR expires_ts > ?)",
            (token_hash, now),
        ).fetchone()
        return dict(row) if row else None


def touch_api_token(token_hash, ts=None):
    init_db()
    ts = ts if ts is not None else int(datetime.now(tz=timezone.utc).timestamp())
    with closing(get_conn()) as conn:
        conn.execute("UPDATE api_tokens SET last_used_ts = ? WHERE token_hash = ?", (ts, token_hash))
        conn.commit()


def list_api_tokens():
    init_db()
    with closing(get_conn()) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT rowid, name, scope, created_by, created_ts, expires_ts, last_used_ts, revoked "
            "FROM api_tokens ORDER BY created_ts DESC"
        )
        return [dict(r) for r in cur.fetchall()]


def revoke_api_token(rowid):
    init_db()
    with closing(get_conn()) as conn:
        conn.execute("UPDATE api_tokens SET revoked = 1 WHERE rowid = ?", (rowid,))
        conn.commit()


def logs_heatmap(days=30):
    """Agrege le nombre d'echantillons de log par jour de semaine (0=dimanche
    ... 6=samedi, convention SQLite strftime('%w')) et par heure locale UTC
    (0-23), sur les `days` derniers jours. Utilise pour la heatmap des
    connexions du Journal (item 32) - une grille simple cote frontend,
    pas de dependance a une lib de graphiques."""
    init_db()
    since = int(datetime.now(tz=timezone.utc).timestamp()) - days * 86400
    with closing(get_conn()) as conn:
        rows = conn.execute(
            "SELECT CAST(strftime('%w', ts, 'unixepoch') AS INTEGER) AS dow, "
            "CAST(strftime('%H', ts, 'unixepoch') AS INTEGER) AS hour, COUNT(*) AS n "
            "FROM logs WHERE ts >= ? GROUP BY dow, hour",
            (since,),
        ).fetchall()
    grid = [[0] * 24 for _ in range(7)]
    for dow, hour, n in rows:
        grid[dow][hour] = n
    return {"days": days, "grid": grid}


def get_peer_last_ip(pubkey):
    init_db()
    with closing(get_conn()) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM peer_last_ip WHERE pubkey = ?", (pubkey,)).fetchone()
        return dict(row) if row else None


def set_peer_last_ip(pubkey, endpoint_ip, country=None, ts=None):
    init_db()
    ts = ts if ts is not None else int(datetime.now(tz=timezone.utc).timestamp())
    with closing(get_conn()) as conn:
        conn.execute(
            "INSERT INTO peer_last_ip (pubkey, endpoint_ip, country, updated_ts) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(pubkey) DO UPDATE SET endpoint_ip = excluded.endpoint_ip, country = excluded.country, updated_ts = excluded.updated_ts",
            (pubkey, endpoint_ip, country, ts),
        )
        conn.commit()


def should_send(rule_key, cooldown_sec, now=None):
    """True si `rule_key` n'a pas ete declenchee depuis `cooldown_sec` (dedup)."""
    init_db()
    now = now if now is not None else int(datetime.now(tz=timezone.utc).timestamp())
    with closing(get_conn()) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT last_sent_ts FROM alert_state WHERE rule_key = ?", (rule_key,)).fetchone()
        if row and (now - row["last_sent_ts"]) < cooldown_sec:
            return False
        conn.execute(
            "INSERT INTO alert_state (rule_key, last_sent_ts) VALUES (?, ?) "
            "ON CONFLICT(rule_key) DO UPDATE SET last_sent_ts = excluded.last_sent_ts",
            (rule_key, now),
        )
        conn.commit()
    _fix_permissions()
    return True


def list_alert_state():
    """Liste les regles actuellement en periode de cooldown (dedup), pour
    affichage/administration depuis le dashboard (voir README 7.7.5) : permet
    de voir POURQUOI une alerte ne s'est pas redeclenchee, et de forcer sa
    reinitialisation sans avoir a passer par sqlite3 en SSH."""
    init_db()
    with closing(get_conn()) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT rule_key, last_sent_ts FROM alert_state ORDER BY last_sent_ts DESC")
        return [dict(r) for r in cur.fetchall()]


def clear_alert_state(rule_key=None):
    """Supprime UNE entree de dedup (`rule_key` precis) ou TOUTES (rule_key=None),
    ce qui force la regle correspondante a pouvoir se redeclencher immediatement
    au prochain passage du cron, meme si son cooldown n'est pas encore ecoule."""
    init_db()
    with closing(get_conn()) as conn:
        if rule_key:
            cur = conn.execute("DELETE FROM alert_state WHERE rule_key = ?", (rule_key,))
        else:
            cur = conn.execute("DELETE FROM alert_state")
        conn.commit()
        deleted = cur.rowcount
    _fix_permissions()
    return deleted


# ---------------------------------------------------------------------
# CLI (utilise par le cron d'ingestion et pour le debug manuel)
# ---------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="BLOCKHash - store.py (metriques long terme + alertes)")
    sub = parser.add_subparsers(dest="action", required=True)

    p_ingest = sub.add_parser("ingest", help="Lit `wg show <if> dump` sur stdin et l'enregistre")
    p_ingest.add_argument("--ts", type=int, default=None)

    sub.add_parser("prune", help="Supprime les echantillons/alertes plus vieux que METRICS_RETENTION_DAYS")
    sub.add_parser("init", help="Cree les tables si necessaire")

    p_series = sub.add_parser("series", help="Debug : affiche la serie pour un pair/plage")
    p_series.add_argument("--pubkey")
    p_series.add_argument("--range", default="1h", choices=list(RANGE_CONFIG))

    sub.add_parser("dedup-list", help="Liste les regles d'alerte actuellement en cooldown")
    p_dedup_clear = sub.add_parser("dedup-clear", help="Reinitialise le cooldown d'une regle (ou de toutes)")
    p_dedup_clear.add_argument("--rule-key", help="Omettre pour tout reinitialiser")

    p_logs = sub.add_parser("logs", help="Debug : affiche une page du journal")
    p_logs.add_argument("--limit", type=int, default=20)
    p_logs.add_argument("--offset", type=int, default=0)
    p_logs.add_argument("--search")

    args = parser.parse_args()

    if args.action == "init":
        init_db()
        print(json.dumps({"ok": True}))
    elif args.action == "ingest":
        ts = args.ts or int(datetime.now(tz=timezone.utc).timestamp())
        dump_text = sys.stdin.read()
        samples_count = ingest_wg_dump(ts, dump_text)
        logs_count = ingest_log_snapshot(ts, dump_text)
        print(json.dumps({"ok": True, "samples": samples_count, "logs": logs_count}))
    elif args.action == "prune":
        retention_days = RETENTION_DAYS
        try:
            import settings_store
            retention_days = int(settings_store.get_settings().get("retention_days", RETENTION_DAYS))
        except Exception:
            pass  # fichier de reglages absent/illisible -> on garde la valeur par defaut (env var)
        prune_old(retention_days=retention_days)
        print(json.dumps({"ok": True, "retention_days": retention_days}))
    elif args.action == "series":
        print(json.dumps(query_series(args.pubkey, args.range)))
    elif args.action == "dedup-list":
        print(json.dumps(list_alert_state()))
    elif args.action == "dedup-clear":
        deleted = clear_alert_state(args.rule_key)
        print(json.dumps({"ok": True, "deleted": deleted}))
    elif args.action == "logs":
        print(json.dumps(query_logs(limit=args.limit, offset=args.offset, search=args.search)))


if __name__ == "__main__":
    main()
