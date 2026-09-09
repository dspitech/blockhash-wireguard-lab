#!/usr/bin/env python3
"""
BLOCKHash - Dashboard WireGuard
API Flask servant les données de supervision (tunnels, journal des
connexions, débit) à l'interface web statique (dashboard/frontend).

Endpoints en lecture (droits sudo restreints a `wg show`) :
  GET /api/overview   -> etat complet (stats + peers + logs + serie de debit)
  GET /api/peers       -> liste des peers avec statut en direct (wg show)
  GET /api/logs         -> journal des connexions (tunnels.csv), pagine
  GET /healthz          -> sonde de disponibilite

Endpoints de gestion des clients (ATTENTION : necessitent la regle
sudoers etendue vers wgctl.py, voir README section 7.6.1 et
scripts/03-install-dashboard.sh) :
  GET    /api/clients                   -> liste des clients (config + statut live)
  POST   /api/clients                   -> ajoute un client (cles + QR + .conf)
  PATCH  /api/clients/<nom>             -> enable/disable/rename/expiry/bandwidth
  DELETE /api/clients/<nom>             -> revocation definitive
  POST   /api/clients/<nom>/regenerate  -> regenere les cles + .conf + QR
  GET    /api/clients/<nom>/config      -> renvoie le .conf + QR existants
  GET    /api/clients/<nom>/history     -> historique dedie (trafic, endpoints, reconnexions)

Authentification : header "X-API-Token" compare a la variable
d'environnement DASHBOARD_TOKEN (voir /etc/blockhash/dashboard.env).
Laisser DASHBOARD_TOKEN vide desactive l'authentification (LAB/demo uniquement).
"""

import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_file, send_from_directory

import alerts
import anomalies
import geoip
import reports
import servers_store
import settings_store
import store
import system_monitor
from wgstate import (
    build_reconnect_stats,
    build_throughput_series,
    load_live_peers as _load_live_peers,
    load_logs,
    load_peer_config,
    reconnect_counts_last_24h,
)

WG_INTERFACE = os.environ.get("WG_INTERFACE", "wg0")
WG_CONF_PATH = Path(os.environ.get("WG_CONF_PATH", "/etc/wireguard/wg0.conf"))
LOG_CSV_PATH = Path(os.environ.get("WG_LOG_CSV", "/var/log/wireguard/tunnels.csv"))
DASHBOARD_TOKEN = os.environ.get("DASHBOARD_TOKEN", "")
FRONTEND_DIR = Path(os.environ.get("FRONTEND_DIR", Path(__file__).resolve().parent.parent / "frontend"))

# wgctl.py / wgops.py sont toujours a cote de ce fichier (deployes ensemble
# par 03-install-dashboard.sh) : jamais de chemin fourni par le client HTTP.
WGCTL_PATH = Path(__file__).resolve().parent / "wgctl.py"
WGOPS_PATH = Path(__file__).resolve().parent / "wgops.py"
# Autorise de desactiver la gestion des clients (lecture seule) tant que
# la regle sudoers etendue n'a pas ete deployee -> voir README 7.6.1.
CLIENT_MANAGEMENT_ENABLED = os.environ.get("CLIENT_MANAGEMENT_ENABLED", "true").lower() != "false"
# Distinct de CLIENT_MANAGEMENT_ENABLED : la rotation de clés serveur et le
# redémarrage du tunnel ont un rayon d'impact bien plus large qu'ajouter un
# client (voir README 7.8.1) - on permet de les désactiver séparément.
SYSTEM_OPS_ENABLED = os.environ.get("SYSTEM_OPS_ENABLED", "true").lower() != "false"
CLIENT_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")

app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="")


# ------------------------------------------------------------------
# Authentification
# ------------------------------------------------------------------
def check_auth():
    if not DASHBOARD_TOKEN:
        return True
    if request.headers.get("X-API-Token") == DASHBOARD_TOKEN:
        return True
    # EventSource (SSE) ne peut pas envoyer d'en-tetes personnalises -> on
    # accepte le jeton en parametre de requete UNIQUEMENT pour ce endpoint
    # precis. Compromis documente (README 7.10.3) : un jeton en query string
    # peut se retrouver dans des logs d'acces - acceptable ici car l'acces
    # au port du dashboard est deja restreint au niveau reseau (section 7.3).
    if request.path == "/api/events/stream" and request.args.get("token") == DASHBOARD_TOKEN:
        return True
    return False


@app.before_request
def enforce_auth():
    if request.path.startswith("/api/") and not check_auth():
        return jsonify({"error": "unauthorized"}), 401


# ------------------------------------------------------------------
# Etat WireGuard (config + live) : voir wgstate.py, partage avec
# alerts.py (cron, sans dependance Flask). Le seuil "en ligne" est
# desormais ajustable a chaud depuis le dashboard (voir /api/settings),
# donc on le relit a chaque appel plutot que de le figer en constante.
# ------------------------------------------------------------------
def load_live_peers():
    threshold = settings_store.get_settings()["online_threshold_sec"]
    return _load_live_peers(online_threshold_sec=threshold)


# ------------------------------------------------------------------
# Routes API - supervision de base
# ------------------------------------------------------------------
APP_VERSION = "1.4.0"


@app.get("/healthz")
def healthz():
    """Verifie que le service repond ET que ses dependances cle sont
    fonctionnelles, pas seulement que Flask est demarre - utile derriere
    un load balancer ou une sonde de supervision externe (voir README
    section 7.10.4)."""
    checks = {}

    checks["wg0_conf_readable"] = WG_CONF_PATH.exists() and os.access(WG_CONF_PATH, os.R_OK)

    try:
        subprocess.run(
            ["wg", "show", WG_INTERFACE, "dump"],
            capture_output=True, text=True, timeout=3, check=True,
        )
        checks["wg_show_responds"] = True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        checks["wg_show_responds"] = False

    try:
        store.query_series(None, "1h")
        checks["metrics_db_reachable"] = True
    except Exception:
        checks["metrics_db_reachable"] = False

    overall_ok = all(checks.values())
    return jsonify({"status": "ok" if overall_ok else "degraded", "checks": checks}), (200 if overall_ok else 503)


@app.get("/api/version")
def api_version():
    return jsonify(
        {
            "version": APP_VERSION,
            "wg_interface": WG_INTERFACE,
            "client_management_enabled": CLIENT_MANAGEMENT_ENABLED,
            "system_ops_enabled": SYSTEM_OPS_ENABLED,
        }
    )


# ------------------------------------------------------------------
# Temps reel : Server-Sent Events (voir README 7.10.3)
#
# Remplace le polling aveugle toutes les 30s par un flux push : le
# navigateur est notifie en quelques secondes d'une connexion/deconnexion
# de client ou d'une nouvelle alerte, sans reinterroger l'API en boucle.
#
# Pas de bus d'evenements en memoire necessaire : chaque connexion SSE
# (potentiellement geree par un worker gunicorn different) relit
# independamment l'etat partage sur disque (wg0.conf, `wg show`, la table
# `alerts` de store.py) toutes les SSE_POLL_INTERVAL_SEC secondes et ne
# pousse un evenement que lorsque quelque chose a reellement change - la
# source de verite reste le systeme de fichiers/le noyau, pas un etat
# applicatif partage entre processus.
# ------------------------------------------------------------------
SSE_POLL_INTERVAL_SEC = 3


def _sse_format(event, data):
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _event_stream():
    last_status = {}
    last_alert_id = 0

    # Amorçage : n'envoie pas d'evenements pour l'etat deja en place au
    # moment de la connexion (sinon chaque ouverture de tiroir "Historique"
    # generait une rafale de faux "peer_connected").
    try:
        for p in load_live_peers():
            last_status[p["public_key"]] = p["status"]
        existing_alerts = store.list_alerts(limit=1)
        if existing_alerts:
            last_alert_id = existing_alerts[0]["id"]
    except Exception:
        pass

    yield _sse_format("ready", {"ok": True})

    while True:
        try:
            peers = load_live_peers()
            for p in peers:
                prev = last_status.get(p["public_key"])
                if prev is not None and prev != p["status"]:
                    if p["status"] == "online":
                        yield _sse_format("peer_connected", {"name": p["name"], "endpoint": p["endpoint"]})
                    elif prev == "online":
                        yield _sse_format("peer_disconnected", {"name": p["name"]})
                last_status[p["public_key"]] = p["status"]

            recent_alerts = store.list_alerts(limit=10)
            new_alerts = [a for a in recent_alerts if a["id"] > last_alert_id]
            for a in reversed(new_alerts):  # chronologique
                yield _sse_format("alert", a)
            if recent_alerts:
                last_alert_id = max(last_alert_id, recent_alerts[0]["id"])
        except GeneratorExit:
            raise
        except Exception as exc:
            yield _sse_format("error", {"message": str(exc)})

        yield ": heartbeat\n\n"  # commentaire SSE : garde la connexion active a travers les proxys
        time.sleep(SSE_POLL_INTERVAL_SEC)


@app.get("/api/events/stream")
def api_events_stream():
    return Response(
        _event_stream(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/peers")
def api_peers():
    return jsonify(load_live_peers())


@app.get("/api/logs")
def api_logs():
    limit = min(int(request.args.get("limit", 50)), 500)
    offset = int(request.args.get("offset", 0))
    search = request.args.get("search") or None
    sort_key = request.args.get("sort_key", "ts")
    sort_dir = request.args.get("sort_dir", "desc")
    status = request.args.get("status")  # "online" | "idle" | "never" | None (= "all")

    pubkeys = None
    if status and status != "all":
        pubkeys = [p["public_key"] for p in load_live_peers() if p["status"] == status]

    result = load_logs(limit=limit, offset=offset, search=search, pubkeys=pubkeys, sort_key=sort_key, sort_dir=sort_dir)
    return jsonify(result)


@app.get("/api/overview")
def api_overview():
    peers = load_live_peers()
    logs = load_logs(limit=300)["rows"]

    active = sum(1 for p in peers if p["status"] == "online")
    total_rx = sum(p["rx_bytes"] for p in peers)
    total_tx = sum(p["tx_bytes"] for p in peers)

    return jsonify(
        {
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "client_management_enabled": CLIENT_MANAGEMENT_ENABLED,
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
# Monitoring avance : debit long terme, systeme, anomalies, reglages
# ------------------------------------------------------------------
@app.get("/api/throughput")
def api_throughput():
    range_key = request.args.get("range", "24h")
    peer_name = request.args.get("peer")

    pubkey = None
    if peer_name:
        config = load_peer_config()
        pubkey = next((pk for pk, info in config.items() if info["name"].lower() == peer_name.lower()), None)
        if not pubkey:
            raise WgctlError(f"Client inconnu : {peer_name}", status=404)

    try:
        series = store.query_series(pubkey, range_key)
    except ValueError as exc:
        raise WgctlError(str(exc), status=422)
    return jsonify({"range": range_key, "peer": peer_name, "series": series})


@app.get("/api/system")
def api_system():
    return jsonify(system_monitor.snapshot())


@app.get("/api/anomalies")
def api_anomalies():
    peers = load_live_peers()
    reconnects = reconnect_counts_last_24h()
    findings = anomalies.detect_all(peers, reconnects, store)
    return jsonify({"anomalies": findings, "generated_at": datetime.now(tz=timezone.utc).isoformat()})


@app.get("/api/geoip")
def api_geoip():
    """Points geolocalises pour la carte des endpoints (onglet Monitoring,
    voir README 7.10.5). Lecture seule, aucun droit sudo necessaire."""
    peers = load_live_peers()
    points = geoip.resolve_endpoints(peers)
    return jsonify({"points": points, "generated_at": datetime.now(tz=timezone.utc).isoformat()})


@app.get("/api/settings")
def api_settings_get():
    return jsonify(settings_store.get_settings())


@app.patch("/api/settings")
def api_settings_update():
    body = request.get_json(silent=True) or {}
    if "online_threshold_sec" in body:
        try:
            value = int(body["online_threshold_sec"])
            if value < 10 or value > 3600:
                raise ValueError
        except (TypeError, ValueError):
            raise WgctlError("online_threshold_sec doit être un entier entre 10 et 3600 (secondes).", status=422)
        body["online_threshold_sec"] = value
    return jsonify(settings_store.update_settings(body))


# ------------------------------------------------------------------
# Alerting configurable (email / Slack / Discord / Telegram)
# Ne necessite PAS la regle sudoers wgctl.py : lecture seule de l'etat
# WireGuard (deja autorisee) + fichier JSON possede par www-data.
# ------------------------------------------------------------------
@app.get("/api/alerts/config")
def api_alerts_config_get():
    return jsonify(alerts.mask_config(alerts.load_config()))


@app.patch("/api/alerts/config")
def api_alerts_config_update():
    body = request.get_json(silent=True) or {}
    updated = alerts.save_config(body)
    return jsonify(alerts.mask_config(updated))


@app.get("/api/alerts/history")
def api_alerts_history():
    limit = int(request.args.get("limit", 50))
    return jsonify(store.list_alerts(limit=limit))


@app.get("/api/alerts/dedup")
def api_alerts_dedup_list():
    """Liste les regles actuellement en cooldown (voir README 7.7.5) : permet
    de comprendre pourquoi une alerte ne s'est pas redeclenchee, sans avoir a
    ouvrir la base SQLite en SSH."""
    now = int(datetime.now(tz=timezone.utc).timestamp())
    entries = store.list_alert_state()
    for e in entries:
        e["age_sec"] = now - e["last_sent_ts"]
    return jsonify(entries)


@app.delete("/api/alerts/dedup")
def api_alerts_dedup_clear_all():
    deleted = store.clear_alert_state(None)
    return jsonify({"ok": True, "deleted": deleted})


@app.delete("/api/alerts/dedup/<path:rule_key>")
def api_alerts_dedup_clear_one(rule_key):
    deleted = store.clear_alert_state(rule_key)
    if not deleted:
        raise WgctlError(f"Aucune entrée de déduplication pour « {rule_key} ».", status=404)
    return jsonify({"ok": True, "deleted": deleted})


@app.post("/api/alerts/test")
def api_alerts_test():
    body = request.get_json(silent=True) or {}
    channel = body.get("channel")
    if channel not in ("email", "slack", "discord", "telegram"):
        raise WgctlError("Canal inconnu (attendu : email, slack, discord, telegram).", status=422)
    try:
        alerts.send_test(channel)
    except Exception as exc:
        raise WgctlError(f"Échec de l'envoi du test : {exc}", status=502)
    return jsonify({"ok": True, "channel": channel})


# ------------------------------------------------------------------
# Gestion des clients (creation, activation, revocation, etc.)
# Tout passe par `sudo -n python3 wgctl.py <action> ...` : ce process
# Flask (www-data) ne touche jamais wg0.conf ni `wg set` lui-meme.
# Necessite la regle sudoers etendue -> voir README section 7.6.1.
# ------------------------------------------------------------------
class ClientManagementDisabled(Exception):
    pass


class SystemOpsDisabled(Exception):
    pass


class WgctlError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def run_privileged(script_path, action, timeout=30, **kwargs):
    """Execute `sudo -n python3 <script_path> <action> --key value ...` et
    parse la reponse JSON. Utilise a la fois par wgctl.py (gestion clients)
    et wgops.py (operations systeme) - meme contrat, memes garanties
    (voir README 7.6.1 / 7.8.1)."""
    cmd = ["sudo", "-n", "python3", str(script_path), action]
    for key, value in kwargs.items():
        if value is None:
            continue
        cmd += [f"--{key.replace('_', '-')}", str(value)]

    try:
        result = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise WgctlError(f"Délai dépassé en attendant {Path(script_path).name}.", status=504)
    except (FileNotFoundError, OSError) as exc:
        # `sudo` absent du PATH, non installe, ou echec de spawn du process -
        # ne doit jamais remonter en 500 brut (voir README 7.10.4 : degradation
        # propre plutot qu'une trace serveur exposee au client).
        raise WgctlError(f"Impossible d'exécuter sudo/{Path(script_path).name} : {exc}", status=502)

    try:
        payload = json.loads(result.stdout.strip() or "{}")
    except json.JSONDecodeError:
        raise WgctlError(
            f"Réponse invalide de {Path(script_path).name} (règle sudoers manquante ou script en erreur) : "
            + (result.stderr.strip()[:300] or "aucun détail"),
            status=502,
        )

    if not payload.get("ok"):
        raise WgctlError(payload.get("error", "Erreur inconnue"), status=400)
    return payload


def run_wgctl(action, **kwargs):
    if not CLIENT_MANAGEMENT_ENABLED:
        raise ClientManagementDisabled()
    return run_privileged(WGCTL_PATH, action, **kwargs)


def run_wgops(action, **kwargs):
    if not SYSTEM_OPS_ENABLED:
        raise SystemOpsDisabled()
    return run_privileged(WGOPS_PATH, action, timeout=60, **kwargs)


def validate_client_name(name):
    if not name or not CLIENT_NAME_RE.match(name):
        raise WgctlError(
            "Nom de client invalide : lettres, chiffres, tirets et underscores uniquement (32 caracteres max).",
            status=422,
        )


@app.errorhandler(WgctlError)
def handle_wgctl_error(err):
    return jsonify({"error": str(err)}), err.status


@app.errorhandler(ClientManagementDisabled)
def handle_disabled(_err):
    return (
        jsonify(
            {
                "error": "La gestion des clients depuis le dashboard est desactivee. "
                "Deployez la regle sudoers etendue (voir README 7.6.1) puis relancez "
                "le service sans CLIENT_MANAGEMENT_ENABLED=false."
            }
        ),
        403,
    )


@app.errorhandler(SystemOpsDisabled)
def handle_system_ops_disabled(_err):
    return (
        jsonify(
            {
                "error": "Les opérations système (sauvegarde/restauration, rotation des clés, "
                "redémarrage du tunnel) sont désactivées depuis le dashboard. Déployez la règle "
                "sudoers étendue vers wgops.py (voir README 7.8.1) puis relancez le service sans "
                "SYSTEM_OPS_ENABLED=false."
            }
        ),
        403,
    )


@app.errorhandler(Exception)
def handle_unexpected_error(err):
    """Filet de securite : une erreur non prevue ne doit jamais renvoyer une
    page d'erreur HTML Werkzeug ni une trace Python brute au client (voir
    README 7.10.4) - seulement du JSON propre, avec le detail dans les logs
    serveur (journalctl -u blockhash-dashboard) pour le diagnostic."""
    from werkzeug.exceptions import HTTPException

    if isinstance(err, HTTPException):
        return jsonify({"error": err.description}), err.code
    app.logger.exception("Erreur non geree")
    return jsonify({"error": "Erreur interne du serveur."}), 500


@app.get("/api/clients")
def api_clients_list():
    return jsonify(load_live_peers())


@app.post("/api/clients")
def api_clients_add():
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    validate_client_name(name)
    expires_days = body.get("expires_days")
    result = run_wgctl("add", name=name, expires_days=expires_days)
    return jsonify(result), 201


@app.patch("/api/clients/<name>")
def api_clients_update(name):
    validate_client_name(name)
    body = request.get_json(silent=True) or {}

    # Chaque champ present dans le corps declenche l'action wgctl correspondante ;
    # plusieurs champs peuvent etre combines dans une seule requete PATCH.
    results = {}

    if "enabled" in body:
        results["enabled"] = run_wgctl("enable" if body["enabled"] else "disable", name=name)

    if "new_name" in body:
        new_name = (body["new_name"] or "").strip()
        validate_client_name(new_name)
        results["renamed"] = run_wgctl("rename", name=name, new_name=new_name)
        name = new_name  # les actions suivantes doivent viser le nouveau nom

    if "expires" in body:
        results["expiry"] = run_wgctl("set-expiry", name=name, expires=body["expires"] or "none")

    if "bw_up_mbit" in body or "bw_down_mbit" in body:
        results["bandwidth"] = run_wgctl(
            "set-bandwidth",
            name=name,
            bw_up=body.get("bw_up_mbit", "none") or "none",
            bw_down=body.get("bw_down_mbit", "none") or "none",
        )

    if not results:
        raise WgctlError(
            "Aucun champ reconnu dans la requete (attendus : enabled, new_name, expires, bw_up_mbit, bw_down_mbit).",
            status=422,
        )
    return jsonify({"ok": True, "name": name, "results": results})


@app.delete("/api/clients/<name>")
def api_clients_revoke(name):
    validate_client_name(name)
    result = run_wgctl("revoke", name=name)
    return jsonify(result)


@app.post("/api/clients/<name>/regenerate")
def api_clients_regenerate(name):
    validate_client_name(name)
    result = run_wgctl("regenerate", name=name)
    return jsonify(result)


@app.get("/api/clients/<name>/config")
def api_clients_config(name):
    validate_client_name(name)
    result = run_wgctl("get-config", name=name)
    return jsonify(result)


@app.get("/api/clients/<name>/history")
def api_clients_history(name):
    validate_client_name(name)
    config = load_peer_config()
    pubkey = next((pk for pk, info in config.items() if info["name"].lower() == name.lower()), None)
    if not pubkey:
        raise WgctlError(f"Client inconnu : {name}", status=404)

    range_key = request.args.get("range", "24h")

    # Reconnexions/dernier endpoint : necessitent le detail par connexion
    # (endpoint vu a chaque capture), interroge directement le pair concerne
    # (SQLite, voir store.query_logs_for_pubkey) plutot que de tout charger.
    result = load_logs(limit=100000, pubkey=pubkey, sort_dir="desc")
    rows = result["rows"]
    rows_chrono = list(reversed(rows))  # load_logs renvoie du plus recent au plus ancien
    stats = build_reconnect_stats(rows_chrono)

    # Debit : base SQLite dediee (store.py), avec de vrais deltas entre
    # echantillons plutot que la somme de compteurs cumulatifs du CSV
    # (voir README 7.7.1) - coherent avec le graphique de l'onglet Monitoring.
    try:
        throughput_series = store.query_series(pubkey, range_key)
    except ValueError:
        throughput_series = store.query_series(pubkey, "24h")
        range_key = "24h"

    return jsonify(
        {
            "name": name,
            "public_key": pubkey,
            "range": range_key,
            "reconnect_count": stats["reconnect_count"],
            "last_endpoint": stats["last_endpoint"],
            "throughput_series": throughput_series,
            "logs": rows[:200],
        }
    )


# ------------------------------------------------------------------
# Administration système : sauvegardes, rotation de clés, redémarrage,
# export d'audit. Tout passe par `sudo -n python3 wgops.py <action>`,
# comme la gestion des clients (voir README 7.8.1). Contrôlé par
# SYSTEM_OPS_ENABLED, séparément de CLIENT_MANAGEMENT_ENABLED : le rayon
# d'impact (rotation de clés, redémarrage) est bien plus large.
# ------------------------------------------------------------------
BACKUP_FILENAME_RE = re.compile(r"^wg0_\d{8}-\d{6}_[A-Za-z0-9_-]{1,40}\.conf$")


def validate_backup_filename(filename):
    if not filename or not BACKUP_FILENAME_RE.match(filename):
        raise WgctlError("Nom de sauvegarde invalide.", status=422)


@app.get("/api/system/backups")
def api_system_backups_list():
    return jsonify(run_wgops("list-backups"))


@app.post("/api/system/backups")
def api_system_backups_create():
    body = request.get_json(silent=True) or {}
    label = (body.get("label") or "manuel").strip()[:40]
    return jsonify(run_wgops("backup", label=label)), 201


@app.get("/api/system/backups/<filename>/diff")
def api_system_backups_diff(filename):
    validate_backup_filename(filename)
    return jsonify(run_wgops("diff-backup", filename=filename))


@app.post("/api/system/backups/<filename>/restore")
def api_system_backups_restore(filename):
    validate_backup_filename(filename)
    return jsonify(run_wgops("restore-backup", filename=filename))


@app.post("/api/system/restart-tunnel")
def api_system_restart_tunnel():
    return jsonify(run_wgops("restart-tunnel"))


@app.post("/api/system/rotate-server-keys")
def api_system_rotate_keys():
    return jsonify(run_wgops("rotate-server-keys"))


@app.get("/api/system/export")
def api_system_export():
    result = run_wgops("export-all")
    zip_path = Path(result["zip_path"])
    if not zip_path.exists():
        raise WgctlError("L'export a été généré mais le fichier est introuvable.", status=500)
    return send_file(
        zip_path,
        as_attachment=True,
        download_name=f"blockhash-audit-{datetime.now(tz=timezone.utc).strftime('%Y%m%d-%H%M%S')}.zip",
        mimetype="application/zip",
    )


# ------------------------------------------------------------------
# Multi-serveurs : supervision agrégée d'autres instances BLOCKHash
# (voir README 7.8.5). Ne nécessite PAS la règle sudoers étendue : ce
# n'est qu'un registre local + des appels HTTP sortants côté serveur.
# ------------------------------------------------------------------
@app.get("/api/servers")
def api_servers_list():
    return jsonify(servers_store.list_servers())


@app.post("/api/servers")
def api_servers_add():
    body = request.get_json(silent=True) or {}
    try:
        result = servers_store.add_server(body.get("name"), body.get("base_url"), body.get("api_token", ""))
    except servers_store.ServerStoreError as exc:
        raise WgctlError(str(exc), status=422)
    return jsonify(result), 201


@app.delete("/api/servers/<name>")
def api_servers_remove(name):
    try:
        result = servers_store.remove_server(name)
    except servers_store.ServerStoreError as exc:
        raise WgctlError(str(exc), status=404)
    return jsonify(result)


@app.get("/api/servers/<name>/overview")
def api_servers_overview(name):
    try:
        return jsonify(servers_store.fetch_overview(name))
    except servers_store.ServerStoreError as exc:
        raise WgctlError(str(exc), status=404)


@app.get("/api/servers/overview-all")
def api_servers_overview_all():
    return jsonify(servers_store.fetch_all_overviews())


# ------------------------------------------------------------------
# Rapports : export PDF générique, rapport hebdomadaire par e-mail
# (réutilise le canal e-mail déjà configuré dans Alertes, voir 7.9.3)
# ------------------------------------------------------------------
@app.post("/api/reports/pdf")
def api_reports_pdf():
    body = request.get_json(silent=True) or {}
    title = (body.get("title") or "Rapport BLOCKHash").strip()[:120]
    subtitle = (body.get("subtitle") or "").strip()[:200]
    columns = body.get("columns") or []
    rows = body.get("rows") or []
    if not columns or not isinstance(columns, list):
        raise WgctlError("Le champ 'columns' est requis (liste non vide).", status=422)
    if not isinstance(rows, list):
        raise WgctlError("Le champ 'rows' doit être une liste.", status=422)

    pdf_bytes = reports.build_table_pdf(title, subtitle, columns, rows)
    from io import BytesIO

    return send_file(
        BytesIO(pdf_bytes),
        as_attachment=True,
        download_name=f"blockhash-{datetime.now(tz=timezone.utc).strftime('%Y%m%d-%H%M%S')}.pdf",
        mimetype="application/pdf",
    )


@app.get("/api/reports/weekly-config")
def api_reports_weekly_config_get():
    return jsonify(reports.load_reports_config())


@app.patch("/api/reports/weekly-config")
def api_reports_weekly_config_update():
    body = request.get_json(silent=True) or {}
    return jsonify(reports.save_reports_config(body))


@app.post("/api/reports/weekly-send")
def api_reports_weekly_send():
    try:
        result = reports.send_weekly_report()
    except Exception as exc:
        raise WgctlError(f"Échec de l'envoi du rapport : {exc}", status=502)
    return jsonify(result)


# ------------------------------------------------------------------
# Conformité : clients actifs sans handshake récent (candidats à la
# révocation). Lecture seule, réutilise load_live_peers() (déjà là).
# ------------------------------------------------------------------
COMPLIANCE_BUCKETS = [90, 60, 30, 15, 7]


@app.get("/api/compliance")
def api_compliance():
    peers = load_live_peers()
    now_ts = int(datetime.now(tz=timezone.utc).timestamp())
    results = []
    for p in peers:
        if not p["enabled"]:
            continue
        if p["seconds_since_handshake"] is None:
            days_inactive = None
        else:
            days_inactive = p["seconds_since_handshake"] // 86400

        bucket = None
        if days_inactive is None:
            bucket = "never"
        else:
            for threshold in COMPLIANCE_BUCKETS:
                if days_inactive >= threshold:
                    bucket = threshold
                    break

        if bucket is None:
            continue  # actif recemment (< 7 jours) -> pas un candidat, on ne le liste pas

        results.append(
            {
                "name": p["name"],
                "allowed_ips": p["allowed_ips"],
                "created": p["created"],
                "last_handshake": p["last_handshake"],
                "days_inactive": days_inactive,
                "bucket": bucket,  # "never" ou un seuil (90/60/30/15/7)
            }
        )

    results.sort(key=lambda r: (r["days_inactive"] is None, r["days_inactive"] or 0), reverse=True)
    return jsonify({"generated_at": datetime.now(tz=timezone.utc).isoformat(), "clients": results})


# ------------------------------------------------------------------
# Frontend statique (index.html, css, js)
# ------------------------------------------------------------------
@app.get("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
