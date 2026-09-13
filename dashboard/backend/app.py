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

Authentification : ecran de connexion du frontend (identifiant + cle,
voir /etc/blockhash/dashboard.env : DASHBOARD_USERNAME / DASHBOARD_PASSWORD_HASH).
POST /api/login echange ces identifiants contre un jeton de session, envoye
ensuite en en-tete "X-API-Token" sur chaque appel (compare a la variable
d'environnement DASHBOARD_TOKEN). Laisser DASHBOARD_TOKEN vide desactive
l'authentification (LAB/demo uniquement, via ALLOW_NO_AUTH=true).
"""

import base64
import json
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, Response, g, jsonify, request, send_file, send_from_directory
from werkzeug.security import check_password_hash

import alerts
import anomalies
import auth
import geoip
import reports
import servers_store
import settings_store
import store
import system_monitor
try:
    import webpush
    WEBPUSH_AVAILABLE = True
except ImportError:
    webpush = None
    WEBPUSH_AVAILABLE = False
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
CONTACT_FIELDS = ("prenom", "email", "telephone", "adresse", "fonction", "tags", "notes")

app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="")


# ------------------------------------------------------------------
# Authentification
# ------------------------------------------------------------------
# SECURITE : un DASHBOARD_TOKEN vide desactive purement et simplement
# l'authentification (voir check_auth ci-dessous) - pratique en lab mais
# catastrophique si ca arrive par erreur en production (ex: fichier .env
# mal genere, variable ecrasee par un outil de deploiement). On refuse
# donc de demarrer dans ce cas, sauf si l'operateur l'assume explicitement
# via ALLOW_NO_AUTH=true (documente README 7.10.6).
ALLOW_NO_AUTH = os.environ.get("ALLOW_NO_AUTH", "false").lower() == "true"
if not DASHBOARD_TOKEN and not ALLOW_NO_AUTH:
    sys.exit(
        "ERREUR FATALE : DASHBOARD_TOKEN est vide. Le dashboard refuse de "
        "demarrer sans authentification (voir /etc/blockhash/dashboard.env). "
        "Pour lancer volontairement sans jeton (lab/demo isole uniquement), "
        "definissez ALLOW_NO_AUTH=true dans le fichier d'environnement."
    )

# Connexion utilisateur/mot de passe (ecran de login du frontend) : le
# dashboard n'est plus expose uniquement sur le tunnel WireGuard (voir
# scripts/03-install-dashboard.sh, etape 7bis) - il est donc joignable
# directement via l'IP publique de la VM. DASHBOARD_TOKEN seul (auparavant
# injecte automatiquement dans le HTML) ne suffit plus comme protection : il
# faut desormais un identifiant + une cle que l'utilisateur saisit lui-meme.
# /api/login echange (username, password) contre DASHBOARD_TOKEN, qui reste
# ensuite utilise tel quel comme jeton de session (voir check_auth) - aucun
# changement pour le reste de l'API.
DASHBOARD_USERNAME = os.environ.get("DASHBOARD_USERNAME", "admin")
DASHBOARD_PASSWORD_HASH = os.environ.get("DASHBOARD_PASSWORD_HASH", "")
if DASHBOARD_TOKEN and not DASHBOARD_PASSWORD_HASH and not ALLOW_NO_AUTH:
    sys.exit(
        "ERREUR FATALE : DASHBOARD_PASSWORD_HASH est vide alors que "
        "DASHBOARD_TOKEN est defini. L'ecran de connexion du dashboard n'a "
        "aucun moyen de verifier un mot de passe (voir "
        "/etc/blockhash/dashboard.env, genere par scripts/03-install-dashboard.sh). "
        "Relancez ce script, ou definissez ALLOW_NO_AUTH=true pour un lab isole."
    )

# Migration vers le modele multi-utilisateurs (items 49/52) : si aucun compte
# n'existe encore en base, importe le compte legacy (dashboard.env) comme
# premier admin. Ne fait rien si des comptes existent deja (mises a jour
# suivantes) - voir auth.ensure_bootstrap_admin.
try:
    auth.ensure_bootstrap_admin(DASHBOARD_USERNAME, DASHBOARD_PASSWORD_HASH)
except Exception as _exc:  # ne doit jamais empecher le demarrage du dashboard
    print(f"[auth] migration bootstrap admin ignoree : {_exc}", file=sys.stderr)

# Journal d'audit dedie, separe des logs applicatifs generaux : trace qui a
# declenche une action qui MODIFIE l'etat du tunnel ou des clients (creation,
# revocation, activation/desactivation, rotation de cles, redemarrage...).
# Volontairement minimaliste (pas de dependance externe) - un simple fichier
# append-only, un evenement par ligne, lisible par `journalctl`/`grep`.
AUDIT_LOG_PATH = Path(os.environ.get("AUDIT_LOG_PATH", "/var/log/wireguard/audit.log"))
audit_logger = logging.getLogger("blockhash.audit")
audit_logger.setLevel(logging.INFO)
if not audit_logger.handlers:
    try:
        _audit_handler = logging.FileHandler(AUDIT_LOG_PATH)
        _audit_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        audit_logger.addHandler(_audit_handler)
    except OSError:
        # Repertoire pas encore prepare (permissions) : on degrade vers
        # stderr plutot que de faire planter l'appli pour un souci de log.
        audit_logger.addHandler(logging.StreamHandler())


def audit(action, **fields):
    detail = " ".join(f"{k}={v!r}" for k, v in fields.items())
    audit_logger.info("ip=%s action=%s %s", request.remote_addr, action, detail)


# Verrouillage anti force-brute, en memoire (process unique gunicorn -w 2 ->
# approximatif entre workers mais suffisant : l'objectif est de ralentir un
# script, pas de garantir une precision distribuee). Cle = IP source.
_FAILED_AUTH = {}  # ip -> {"count": int, "locked_until": float}
AUTH_MAX_ATTEMPTS = int(os.environ.get("AUTH_MAX_ATTEMPTS", "8"))
AUTH_LOCKOUT_SECONDS = int(os.environ.get("AUTH_LOCKOUT_SECONDS", "300"))


def _record_auth_failure(ip, max_attempts=None, lockout_seconds=None):
    max_attempts = AUTH_MAX_ATTEMPTS if max_attempts is None else max_attempts
    lockout_seconds = AUTH_LOCKOUT_SECONDS if lockout_seconds is None else lockout_seconds
    entry = _FAILED_AUTH.setdefault(ip, {"count": 0, "locked_until": 0.0})
    entry["count"] += 1
    if entry["count"] >= max_attempts:
        entry["locked_until"] = time.time() + lockout_seconds
        audit("auth_lockout", attempts=entry["count"], lockout_seconds=lockout_seconds, key=ip)
        try:
            alert_cfg = alerts.load_config()
            if alert_cfg.get("enabled") and alert_cfg["rules"].get("failed_auth_attempts"):
                rule_key = f"failed_auth:{ip}"
                cooldown = alert_cfg["cooldowns_sec"].get("failed_auth_attempts", 300)
                if store.should_send(rule_key, cooldown, now=int(time.time())):
                    msg = f"{entry['count']} tentatives d'authentification échouées depuis {ip} — verrouillage {lockout_seconds}s."
                    alerts.dispatch(alert_cfg, "BLOCKHash - Tentatives échouées", msg, level="critical", rule_key=rule_key)
        except Exception:
            pass  # une alerte ratee ne doit jamais bloquer la reponse d'authentification


def _record_auth_success(ip):
    _FAILED_AUTH.pop(ip, None)


def _is_locked_out(ip, max_attempts=None, lockout_seconds=None):
    entry = _FAILED_AUTH.get(ip)
    if not entry:
        return False
    if entry["locked_until"] and time.time() < entry["locked_until"]:
        return True
    if entry["locked_until"] and time.time() >= entry["locked_until"]:
        _FAILED_AUTH.pop(ip, None)  # periode ecoulee : on reinitialise
    return False


def check_auth():
    if not DASHBOARD_TOKEN and not store.list_users():
        return True  # ALLOW_NO_AUTH ou aucune auth configuree du tout

    token = request.headers.get("X-API-Token")
    if not token and request.path == "/api/events/stream":
        # EventSource (SSE) ne peut pas envoyer d'en-tetes personnalises -> on
        # accepte le jeton en parametre de requete UNIQUEMENT pour ce endpoint
        # precis. Compromis documente (README 7.10.3) : un jeton en query
        # string peut se retrouver dans des logs d'acces - acceptable ici car
        # l'acces au dashboard est de toute facon restreint au tunnel
        # WireGuard (voir scripts/03-install-dashboard.sh, etape 7bis).
        token = request.args.get("token")
    if not token:
        return False

    # 1. Jeton legacy partage (retro-compatibilite le temps de la migration -
    #    voir auth.py). Traite comme un admin implicite.
    if DASHBOARD_TOKEN and token == DASHBOARD_TOKEN:
        g.current_user = {"username": "legacy-token", "role": "admin"}
        return True

    # 2. Session utilisateur (creee par /api/login)
    user = auth.resolve_session_token(token)
    if user:
        g.current_user = user
        return True

    # 3. Token API scope (cree via /api/tokens)
    user = auth.resolve_api_token(token)
    if user:
        g.current_user = user
        return True

    return False


@app.before_request
def enforce_auth():
    if not request.path.startswith("/api/"):
        return None
    # /api/login est le seul endpoint joignable SANS jeton deja en main : il
    # sert justement a en obtenir un a partir d'un identifiant + mot de passe.
    # Il applique son propre controle (voir api_login), y compris le meme
    # verrouillage anti force-brute que ci-dessous.
    if request.path == "/api/login":
        return None
    ip = request.remote_addr
    if _is_locked_out(ip):
        return jsonify({"error": "too_many_attempts", "retry_after_seconds": AUTH_LOCKOUT_SECONDS}), 429
    if not check_auth():
        _record_auth_failure(ip)
        return jsonify({"error": "unauthorized"}), 401
    _record_auth_success(ip)

    # Controle de permission par role (items 49/52) : g.current_user est
    # renseigne par check_auth() ci-dessus pour toute requete authentifiee.
    required = auth.required_role_for(request.method, request.path)
    user_role = g.current_user["role"] if hasattr(g, "current_user") else "admin"
    if auth.ROLE_RANK.get(user_role, 0) < auth.ROLE_RANK.get(required, 2):
        audit("permission_denied", path=request.path, method=request.method, role=user_role, required=required)
        return jsonify({"error": "insufficient_role", "required": required}), 403
    return None


@app.post("/api/login")
def api_login():
    """Echange (username, password) contre un jeton de SESSION propre a cet
    utilisateur (et non plus le jeton statique partage DASHBOARD_TOKEN - voir
    auth.py). Le frontend stocke ce jeton en localStorage (voir
    app.js:authHeaders) et l'envoie ensuite en en-tete X-API-Token sur chaque
    appel, exactement comme avant l'introduction des comptes multiples."""
    ip = request.remote_addr
    if _is_locked_out(ip):
        return jsonify({"error": "too_many_attempts", "retry_after_seconds": AUTH_LOCKOUT_SECONDS}), 429

    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""

    user = auth.authenticate(username, password) if username and password else None
    if not user:
        _record_auth_failure(ip)
        audit("login_failed", username=username)
        return jsonify({"error": "invalid_credentials"}), 401

    _record_auth_success(ip)
    store.touch_user_login(user["username"])
    audit("login_success", username=user["username"], role=user["role"])
    token = auth.create_session_token(user["username"])
    return jsonify({"token": token, "username": user["username"], "role": user["role"]})


@app.get("/api/auth/me")
def api_auth_me():
    user = getattr(g, "current_user", None) or {"username": DASHBOARD_USERNAME, "role": "admin"}
    return jsonify(user)


@app.get("/api/users")
def api_users_list():
    return jsonify(store.list_users())


@app.post("/api/users")
def api_users_create():
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    role = body.get("role") or "reader"
    if not CLIENT_NAME_RE.match(username):
        raise WgctlError("Nom d'utilisateur invalide : lettres, chiffres, tirets et underscores uniquement.", status=422)
    if role not in auth.VALID_ROLES:
        raise WgctlError(f"Rôle invalide (attendus : {', '.join(auth.VALID_ROLES)}).", status=422)
    if len(password) < 8:
        raise WgctlError("Le mot de passe doit contenir au moins 8 caractères.", status=422)
    if store.get_user(username):
        raise WgctlError(f"Un utilisateur nommé « {username} » existe déjà.", status=409)
    store.create_user(username, auth.create_password_hash(password), role)
    audit("user_created", username=username, role=role, by=g.current_user["username"])
    return jsonify({"ok": True, "username": username, "role": role}), 201


@app.patch("/api/users/<username>")
def api_users_update(username):
    body = request.get_json(silent=True) or {}
    if not store.get_user(username):
        raise WgctlError(f"Utilisateur inconnu : {username}", status=404)

    # Garde-fou : on ne doit jamais pouvoir se retrouver sans aucun admin actif
    # (verrou irrecuperable sans acces SSH pour repasser par dashboard.env).
    demoting = "role" in body and body["role"] != "admin"
    deactivating = body.get("active") is False
    if (demoting or deactivating) and store.count_active_admins(exclude_username=username) == 0:
        raise WgctlError(
            "Impossible : ce serait le dernier compte admin actif. Promouvez un autre compte d'abord.",
            status=422,
        )

    if "role" in body and body["role"] not in auth.VALID_ROLES:
        raise WgctlError(f"Rôle invalide (attendus : {', '.join(auth.VALID_ROLES)}).", status=422)

    password_hash = None
    if body.get("password"):
        if len(body["password"]) < 8:
            raise WgctlError("Le mot de passe doit contenir au moins 8 caractères.", status=422)
        password_hash = auth.create_password_hash(body["password"])

    store.update_user(
        username,
        role=body.get("role"),
        active=body.get("active"),
        password_hash=password_hash,
    )
    if password_hash or body.get("active") is False:
        store.delete_sessions_for_user(username)  # force une reconnexion apres changement de mot de passe/desactivation
    audit("user_updated", username=username, by=g.current_user["username"], fields=list(body.keys()))
    return jsonify({"ok": True, "username": username})


@app.delete("/api/users/<username>")
def api_users_delete(username):
    if username == g.current_user["username"]:
        raise WgctlError("Impossible de supprimer votre propre compte pendant que vous êtes connecté avec.", status=422)
    if not store.get_user(username):
        raise WgctlError(f"Utilisateur inconnu : {username}", status=404)
    if store.count_active_admins(exclude_username=username) == 0:
        raise WgctlError("Impossible : ce serait le dernier compte admin actif.", status=422)
    store.delete_user(username)
    audit("user_deleted", username=username, by=g.current_user["username"])
    return jsonify({"ok": True})


@app.get("/api/tokens")
def api_tokens_list():
    return jsonify(store.list_api_tokens())


@app.post("/api/tokens")
def api_tokens_create():
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()[:60]
    scope = body.get("scope") or "reader"
    expires_days = body.get("expires_days")
    if not name:
        raise WgctlError("Un nom est requis pour identifier ce token.", status=422)
    if scope not in auth.VALID_ROLES:
        raise WgctlError(f"Scope invalide (attendus : {', '.join(auth.VALID_ROLES)}).", status=422)
    expires_ts = None
    if expires_days:
        expires_ts = int(datetime.now(tz=timezone.utc).timestamp()) + int(expires_days) * 86400

    raw_token = auth.generate_raw_token("bhtok")
    store.create_api_token(auth.hash_token(raw_token), name, scope, g.current_user["username"], expires_ts=expires_ts)
    audit("api_token_created", name=name, scope=scope, by=g.current_user["username"])
    # Le token en clair n'est renvoye QU'ICI, une seule fois - il n'est pas
    # recuperable ensuite (seule son empreinte est stockee, voir auth.py).
    return jsonify({"ok": True, "token": raw_token, "name": name, "scope": scope}), 201


@app.delete("/api/tokens/<int:rowid>")
def api_tokens_revoke(rowid):
    store.revoke_api_token(rowid)
    audit("api_token_revoked", rowid=rowid, by=g.current_user["username"])
    return jsonify({"ok": True})


# Capture generique de toute action MUTANTE (POST/PATCH/DELETE) sur l'API,
# plutot qu'un appel audit() manuel route par route : garantit qu'aucune
# route actuelle ou future (creation client, rotation de cles, restauration
# de sauvegarde...) n'echappe au journal, meme en cas d'oubli lors d'un
# prochain developpement. Les routes en lecture (GET) ne sont pas journalisees
# ici pour ne pas noyer le signal utile dans du bruit de consultation.
@app.after_request
def log_mutations(response):
    if request.path.startswith("/api/") and request.method in ("POST", "PATCH", "DELETE"):
        audit(
            "api_mutation",
            method=request.method,
            path=request.path,
            status=response.status_code,
        )
    return response


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
        existing_alerts = store.list_alerts(limit=1)["rows"]
        if existing_alerts:
            last_alert_id = existing_alerts[0]["id"]
    except Exception:
        pass

    yield _sse_format("ready", {"ok": True})

    while True:
        try:
            peers = load_live_peers()
            alert_cfg = None  # charge paresseusement, une seule fois par iteration si besoin
            for p in peers:
                prev = last_status.get(p["public_key"])
                if prev is not None and prev != p["status"]:
                    transition = None
                    if p["status"] == "online":
                        transition = "connected"
                        yield _sse_format("peer_connected", {"name": p["name"], "endpoint": p["endpoint"]})
                    elif prev == "online":
                        transition = "disconnected"
                        yield _sse_format("peer_disconnected", {"name": p["name"]})

                    # Regle d'alerte "connexion/deconnexion" : evenementielle
                    # (contrairement aux autres regles, evaluees par le cron
                    # toutes les 5 min) - detectee ici, au fil de l'eau, par
                    # chaque connexion SSE ouverte. store.should_send() deduplique
                    # proprement meme si plusieurs onglets/workers observent la
                    # meme transition au meme moment (voir README 7.7.6).
                    if transition:
                        try:
                            if alert_cfg is None:
                                alert_cfg = alerts.load_config()
                            if alert_cfg.get("enabled") and alert_cfg["rules"].get("connect_disconnect"):
                                rule_key = f"{transition}:{p['public_key']}"
                                cooldown = alert_cfg["cooldowns_sec"].get("connect_disconnect", 60)
                                if store.should_send(rule_key, cooldown, now=int(time.time())):
                                    verb = "s'est connecté" if transition == "connected" else "s'est déconnecté"
                                    msg = f"Client « {p['name']} » {verb}" + (f" ({p['endpoint']})" if p.get("endpoint") and transition == "connected" else ".")
                                    alerts.dispatch(
                                        alert_cfg,
                                        f"BLOCKHash - {'Connexion' if transition == 'connected' else 'Déconnexion'}",
                                        msg,
                                        level="info",
                                        rule_key=rule_key,
                                        peer_name=p["name"],
                                    )

                            # Regle "hors plage horaire" : ne concerne que les
                            # connexions (pas les deconnexions), evaluee ici en
                            # temps reel car le cron (5 min) manquerait souvent
                            # la fenetre horaire exacte de la connexion.
                            off_hours_cfg = alert_cfg["rules"].get("off_hours") or {}
                            if transition == "connected" and off_hours_cfg.get("enabled"):
                                now_local = datetime.now().time()
                                start = datetime.strptime(off_hours_cfg.get("start", "22:00"), "%H:%M").time()
                                end = datetime.strptime(off_hours_cfg.get("end", "06:00"), "%H:%M").time()
                                in_window = (start <= now_local or now_local <= end) if start > end else (start <= now_local <= end)
                                if in_window:
                                    rule_key = f"off_hours:{p['public_key']}"
                                    cooldown = alert_cfg["cooldowns_sec"].get("off_hours", 60)
                                    if store.should_send(rule_key, cooldown, now=int(time.time())):
                                        msg = f"Client « {p['name']} » s'est connecté hors plage horaire autorisée ({off_hours_cfg.get('start')}–{off_hours_cfg.get('end')})."
                                        alerts.dispatch(alert_cfg, "BLOCKHash - Connexion hors horaires", msg, level="warning", rule_key=rule_key, peer_name=p["name"])
                        except Exception:
                            pass  # une alerte ratee ne doit jamais casser le flux SSE

                last_status[p["public_key"]] = p["status"]

            recent_alerts = store.list_alerts(limit=10)["rows"]
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
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    volume_min_mb = request.args.get("volume_min_mb")
    volume_max_mb = request.args.get("volume_max_mb")

    pubkeys = None
    if status and status != "all":
        pubkeys = [p["public_key"] for p in load_live_peers() if p["status"] == status]

    result = load_logs(
        limit=limit, offset=offset, search=search, pubkeys=pubkeys, sort_key=sort_key, sort_dir=sort_dir,
        ts_from=int(date_from) if date_from else None,
        ts_to=int(date_to) if date_to else None,
        volume_min=int(float(volume_min_mb) * 1_000_000) if volume_min_mb else None,
        volume_max=int(float(volume_max_mb) * 1_000_000) if volume_max_mb else None,
    )
    return jsonify(result)


@app.get("/api/logs/heatmap")
def api_logs_heatmap():
    days = min(int(request.args.get("days", 30)), 365)
    return jsonify(store.logs_heatmap(days=days))


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
    return jsonify(system_monitor.snapshot(include_ping=request.args.get("ping") == "true"))


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
    if "retention_days" in body and body["retention_days"] is not None:
        try:
            value = int(body["retention_days"])
            if value < 1 or value > 3650:
                raise ValueError
        except (TypeError, ValueError):
            raise WgctlError("retention_days doit être un entier entre 1 et 3650 jours (ou null pour illimité).", status=422)
        body["retention_days"] = value
    return jsonify(settings_store.update_settings(body))


@app.post("/api/system/purge")
def api_system_purge():
    """Purge manuelle immediate (en plus du cron quotidien) : supprime logs,
    echantillons de debit et historique d'alertes plus vieux que
    retention_days. Tourne dans le process Flask (pas besoin de sudo,
    store.py n'ecrit que dans sa propre base SQLite)."""
    settings = settings_store.get_settings()
    retention_days = settings.get("retention_days") or 3650
    store.prune_old(retention_days=retention_days)
    audit("manual_purge", retention_days=retention_days)
    return jsonify({"ok": True, "retention_days": retention_days})


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


@app.get("/api/push/vapid-public-key")
def api_push_vapid_public_key():
    if not WEBPUSH_AVAILABLE:
        return jsonify({"available": False}), 200
    return jsonify({"available": True, "public_key": webpush.public_key_b64url()})


@app.post("/api/push/subscribe")
def api_push_subscribe():
    if not WEBPUSH_AVAILABLE:
        raise WgctlError("Web Push indisponible : dépendances non installées côté serveur (pywebpush).", status=503)
    body = request.get_json(silent=True) or {}
    endpoint = body.get("endpoint")
    keys = body.get("keys") or {}
    if not endpoint or not keys.get("p256dh") or not keys.get("auth"):
        raise WgctlError("Abonnement Web Push invalide (endpoint/keys manquants).", status=422)
    store.save_push_subscription(endpoint, keys["p256dh"], keys["auth"])
    return jsonify({"ok": True}), 201


@app.post("/api/push/unsubscribe")
def api_push_unsubscribe():
    body = request.get_json(silent=True) or {}
    if body.get("endpoint"):
        store.delete_push_subscription(body["endpoint"])
    return jsonify({"ok": True})


@app.post("/api/push/test")
def api_push_test():
    if not WEBPUSH_AVAILABLE:
        raise WgctlError("Web Push indisponible : dépendances non installées côté serveur (pywebpush).", status=503)
    result = webpush.broadcast("BLOCKHash - Test", "Ceci est une notification de test.", url="/")
    return jsonify(result)
def api_alerts_history():
    limit = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))
    severity = request.args.get("severity") or None
    peer_name = request.args.get("client") or None
    rule = request.args.get("rule") or None
    ts_from = request.args.get("date_from")
    ts_to = request.args.get("date_to")
    archived = request.args.get("archived")
    return jsonify(store.list_alerts(
        limit=limit, offset=offset, severity=severity, peer_name=peer_name, rule=rule,
        ts_from=int(ts_from) if ts_from else None,
        ts_to=int(ts_to) if ts_to else None,
        archived=(archived == "true") if archived in ("true", "false") else None,
    ))


@app.get("/api/alerts/history/export")
def api_alerts_history_export():
    data = store.list_alerts(limit=10000, offset=0)
    header = "horodatage,severite,regle,client,message"
    lines = [header]
    for a in data["rows"]:
        ts_iso = datetime.fromtimestamp(a["ts"], tz=timezone.utc).isoformat()
        cells = [ts_iso, a["level"], a.get("rule_key") or "", a.get("peer_name") or "", a["message"]]
        lines.append(",".join('"' + str(c).replace('"', '""') + '"' for c in cells))
    return Response(
        "\n".join(lines) + "\n",
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=alertes.csv"},
    )


@app.patch("/api/alerts/history/<int:alert_id>")
def api_alerts_history_update(alert_id):
    body = request.get_json(silent=True) or {}
    if body.get("read"):
        store.mark_alert_read(alert_id)
    if "archived" in body:
        store.set_alert_archived(alert_id, archived=bool(body["archived"]))
    return jsonify({"ok": True, "id": alert_id})


@app.delete("/api/alerts/history/<int:alert_id>")
def api_alerts_history_delete(alert_id):
    store.delete_alert(alert_id)
    return jsonify({"ok": True, "id": alert_id})


@app.get("/api/alerts/stats")
def api_alerts_stats():
    days = min(int(request.args.get("days", 7)), 90)
    return jsonify(store.alerts_stats(days=days))


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


@app.get("/api/clients/export")
def api_clients_export():
    status = request.args.get("status")
    peers = load_live_peers()
    if status and status != "all":
        peers = [p for p in peers if (p["status"] if p["enabled"] else "disabled") == status]

    columns = ["name", "status", "allowed_ips", "prenom", "email", "telephone", "adresse", "fonction", "created", "expires"]
    lines = [",".join(columns)]

    def esc(value):
        s = "" if value is None else str(value)
        return '"' + s.replace('"', '""') + '"' if ("," in s or '"' in s) else s

    for p in peers:
        row = dict(p)
        row["status"] = row["status"] if row["enabled"] else "disabled"
        lines.append(",".join(esc(row.get(c)) for c in columns))

    return Response(
        "\n".join(lines) + "\n",
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=clients-{datetime.now(tz=timezone.utc).strftime('%Y%m%d-%H%M%S')}.csv"},
    )


@app.post("/api/clients")
def api_clients_add():
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    validate_client_name(name)
    expires_days = body.get("expires_days")
    contact = {f: (body.get(f) or "").strip() or None for f in CONTACT_FIELDS}
    if "rgpd_consent" in body:
        contact["rgpd_consent"] = "true" if body["rgpd_consent"] else "false"
    result = run_wgctl("add", name=name, expires_days=expires_days, **contact)
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

    if any(f in body for f in CONTACT_FIELDS) or "rgpd_consent" in body:
        contact = {f: body[f] for f in CONTACT_FIELDS if f in body}
        if "rgpd_consent" in body:
            contact["rgpd_consent"] = "true" if body["rgpd_consent"] else "false"
        results["contact"] = run_wgctl("set-contact", name=name, **contact)

    if not results:
        raise WgctlError(
            "Aucun champ reconnu dans la requete (attendus : enabled, new_name, expires, bw_up_mbit, "
            "bw_down_mbit, " + ", ".join(CONTACT_FIELDS) + ").",
            status=422,
        )
    return jsonify({"ok": True, "name": name, "results": results})


@app.post("/api/clients/bulk")
def api_clients_bulk_add():
    """Creation groupee : chaque ligne est traitee independamment (un echec
    n'interrompt pas les suivantes), avec un rapport detaille par ligne -
    utilise par l'import CSV et par le formulaire multi-lignes du frontend."""
    body = request.get_json(silent=True) or {}
    rows = body.get("clients")
    if not isinstance(rows, list) or not rows:
        raise WgctlError("Le champ 'clients' est requis (liste non vide).", status=422)
    if len(rows) > 500:
        raise WgctlError("500 clients maximum par import.", status=422)

    dry_run = bool(body.get("dry_run"))
    created, errors = [], []
    for i, row in enumerate(rows):
        raw_name = (row.get("name") or row.get("nom") or "").strip()
        try:
            validate_client_name(raw_name)
        except WgctlError as exc:
            errors.append({"row": i + 1, "name": raw_name, "error": str(exc)})
            continue
        if dry_run:
            created.append({"row": i + 1, "name": raw_name})
            continue
        try:
            contact = {f: (row.get(f) or "").strip() or None for f in CONTACT_FIELDS}
            result = run_wgctl("add", name=raw_name, expires_days=row.get("expires_days"), **contact)
            created.append({"row": i + 1, "name": raw_name, "allowed_ips": result.get("allowed_ips")})
        except WgctlError as exc:
            errors.append({"row": i + 1, "name": raw_name, "error": str(exc)})

    return jsonify({"ok": True, "dry_run": dry_run, "created": created, "errors": errors})


@app.get("/api/clients/import-template")
def api_clients_import_template():
    header = "nom,prenom,email,telephone,adresse,fonction,expires_days"
    example = "jdupont,Jean Dupont,jean.dupont@example.com,+33612345678,\"12 rue de Paris, 75001 Paris\",Technicien,365"
    csv_text = header + "\n" + example + "\n"
    return Response(
        csv_text,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=modele-import-clients.csv"},
    )


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


@app.get("/api/clients/<name>/gdpr-export")
def api_clients_gdpr_export(name):
    """Export complet des donnees d'un client (profil + historique de
    connexions), en reponse a une demande d'acces RGPD. Le client garde le
    controle : le consentement (rgpd_consent) et sa date sont inclus tels
    quels dans l'export, sans interpretation."""
    validate_client_name(name)
    peer = next((p for p in load_live_peers() if p["name"].lower() == name.lower()), None)
    if not peer:
        raise WgctlError(f"Client inconnu : {name}", status=404)

    result = load_logs(limit=1000, pubkey=peer["public_key"], sort_dir="desc")
    audit("gdpr_export", client=name)

    export = {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "profile": {k: peer.get(k) for k in (
            "name", "prenom", "email", "telephone", "adresse", "fonction", "tags", "notes",
            "allowed_ips", "created", "expires", "rgpd_consent",
        )},
        "connection_history": result["rows"],
    }
    return Response(
        json.dumps(export, indent=2, ensure_ascii=False),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename={name}-export-rgpd.json"},
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
    description = (body.get("description") or "").strip()[:500] or None
    return jsonify(run_wgops("backup", label=label, description=description)), 201


@app.get("/api/system/backups/<filename>/diff")
def api_system_backups_diff(filename):
    validate_backup_filename(filename)
    return jsonify(run_wgops("diff-backup", filename=filename))


def _verify_current_user_password(password):
    """Verifie `password` contre le compte reellement connecte (voir
    g.current_user, renseigne par check_auth). Repli sur DASHBOARD_PASSWORD_HASH
    uniquement si la requete est authentifiee via le jeton legacy partage ou
    un token API (qui n'ont pas de mot de passe propre a re-verifier)."""
    if not password:
        return False
    current = getattr(g, "current_user", None)
    if current and not current["username"].startswith("token:") and current["username"] != "legacy-token":
        user = store.get_user(current["username"])
        if not user:
            return False
        try:
            return check_password_hash(user["password_hash"], password)
        except ValueError:
            return False
    if DASHBOARD_PASSWORD_HASH:
        try:
            return check_password_hash(DASHBOARD_PASSWORD_HASH, password)
        except ValueError:
            return False
    return False


@app.post("/api/system/backups/<filename>/restore")
def api_system_backups_restore(filename):
    validate_backup_filename(filename)
    body = request.get_json(silent=True) or {}
    password = body.get("password") or ""
    ip = request.remote_addr
    lock_key = f"restore:{ip}"

    if _is_locked_out(lock_key, max_attempts=BACKUP_DOWNLOAD_MAX_ATTEMPTS, lockout_seconds=BACKUP_DOWNLOAD_LOCKOUT_SECONDS):
        return jsonify({"error": "too_many_attempts", "retry_after_seconds": BACKUP_DOWNLOAD_LOCKOUT_SECONDS}), 429

    if not _verify_current_user_password(password):
        _record_auth_failure(lock_key, max_attempts=BACKUP_DOWNLOAD_MAX_ATTEMPTS, lockout_seconds=BACKUP_DOWNLOAD_LOCKOUT_SECONDS)
        audit("backup_restore_denied", filename=filename)
        return jsonify({"error": "invalid_password"}), 401

    _record_auth_success(lock_key)
    result = run_wgops("restore-backup", filename=filename)
    audit("backup_restored", filename=filename, safety_backup=result.get("safety_backup"))
    return jsonify(result)


BACKUP_DOWNLOAD_MAX_ATTEMPTS = 3
BACKUP_DOWNLOAD_LOCKOUT_SECONDS = 300


@app.post("/api/system/backups/<filename>/download")
def api_system_backups_download(filename):
    """Telechargement d'une sauvegarde : exige de re-saisir le mot de passe
    admin (meme si le jeton de session est deja valide), avec son propre
    compteur anti force-brute (3 essais / 5 min, distinct du verrouillage de
    login) et un log d'audit dedie (qui a telecharge quoi, quand)."""
    validate_backup_filename(filename)
    ip = request.remote_addr
    lock_key = f"backup:{ip}"

    if _is_locked_out(lock_key, max_attempts=BACKUP_DOWNLOAD_MAX_ATTEMPTS, lockout_seconds=BACKUP_DOWNLOAD_LOCKOUT_SECONDS):
        return jsonify({"error": "too_many_attempts", "retry_after_seconds": BACKUP_DOWNLOAD_LOCKOUT_SECONDS}), 429

    body = request.get_json(silent=True) or {}
    password = body.get("password") or ""

    if not _verify_current_user_password(password):
        _record_auth_failure(lock_key, max_attempts=BACKUP_DOWNLOAD_MAX_ATTEMPTS, lockout_seconds=BACKUP_DOWNLOAD_LOCKOUT_SECONDS)
        audit("backup_download_denied", filename=filename)
        return jsonify({"error": "invalid_password"}), 401

    _record_auth_success(lock_key)
    result = run_wgops("download-backup", filename=filename)
    content = base64.b64decode(result["content_base64"])
    audit("backup_downloaded", filename=filename, size_bytes=len(content))
    return Response(
        content,
        mimetype="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.post("/api/system/restart-tunnel")
def api_system_restart_tunnel():
    affected = sum(1 for p in load_live_peers() if p["status"] == "online")
    result = run_wgops("restart-tunnel")
    audit("tunnel_restarted", clients_disconnected=affected)
    result["clients_disconnected"] = affected
    return jsonify(result)


@app.post("/api/system/rotate-server-keys")
def api_system_rotate_keys():
    affected = len(load_live_peers())
    result = run_wgops("rotate-server-keys")
    audit("server_keys_rotated", clients_affected=affected)
    result["clients_affected"] = affected
    return jsonify(result)


@app.get("/api/system/audit")
def api_system_audit():
    """Lit le journal d'audit append-only (voir AUDIT_LOG_PATH) et renvoie
    les entrees les plus recentes en premier, avec pagination simple. Lecture
    seule d'un fichier texte : aucun risque, meme si le fichier grossit
    beaucoup (on ne lit que ce qui est demande)."""
    limit = min(int(request.args.get("limit", 50)), 500)
    offset = int(request.args.get("offset", 0))
    if not AUDIT_LOG_PATH.exists():
        return jsonify({"rows": [], "total": 0})
    lines = AUDIT_LOG_PATH.read_text(errors="ignore").splitlines()
    lines.reverse()  # plus recent en premier
    total = len(lines)
    page = lines[offset:offset + limit]
    return jsonify({"rows": [{"raw": line} for line in page], "total": total})


@app.get("/api/system/audit/export")
def api_system_audit_export():
    if not AUDIT_LOG_PATH.exists():
        return Response("", mimetype="text/plain", headers={"Content-Disposition": "attachment; filename=audit.log"})
    return Response(
        AUDIT_LOG_PATH.read_bytes(),
        mimetype="text/plain",
        headers={"Content-Disposition": "attachment; filename=audit.log"},
    )
@app.get("/api/system/diagnostics")
def api_system_diagnostics():
    return jsonify(run_wgops("diagnostics"))


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
DEFAULT_COMPLIANCE_POLICIES = {
    "default_inactive_days": 90,
    "by_tag": {"vip": 180, "externe": 30, "audit": 30},
    "exceptions": [],  # noms de clients exclus des controles (a documenter par l'admin)
}


@app.get("/api/compliance/policies")
def api_compliance_policies():
    return jsonify(settings_store.get_settings().get("compliance_policies", DEFAULT_COMPLIANCE_POLICIES))


@app.patch("/api/compliance/policies")
def api_compliance_policies_update():
    body = request.get_json(silent=True) or {}
    current = settings_store.get_settings().get("compliance_policies", DEFAULT_COMPLIANCE_POLICIES)
    current = {**current, **body}
    return jsonify(settings_store.update_settings({"compliance_policies": current})["compliance_policies"])


@app.get("/api/compliance")
def api_compliance():
    policies = settings_store.get_settings().get("compliance_policies", DEFAULT_COMPLIANCE_POLICIES)
    exceptions = set(policies.get("exceptions", []))
    by_tag = policies.get("by_tag", {})
    default_threshold = policies.get("default_inactive_days", 90)

    peers = load_live_peers()
    results = []
    for p in peers:
        if not p["enabled"] or p["name"] in exceptions:
            continue
        if p["seconds_since_handshake"] is None:
            days_inactive = None
        else:
            days_inactive = p["seconds_since_handshake"] // 86400

        # Seuil effectif : le plus permissif des tags du client l'emporte
        # (un client marque a la fois #vip et #audit garde le seuil le plus
        # long, cf. "politiques par tag de client" - une exception documentee
        # via #tag est une politique, pas un contournement silencieux).
        client_tags = [t.strip().lstrip("#") for t in (p.get("tags") or "").split(",") if t.strip()]
        effective_threshold = max([by_tag.get(t, 0) for t in client_tags] + [0]) or default_threshold

        bucket = None
        if days_inactive is None:
            bucket = "never"
        elif days_inactive >= effective_threshold:
            for threshold in COMPLIANCE_BUCKETS:
                if days_inactive >= threshold:
                    bucket = threshold
                    break
            bucket = bucket or effective_threshold

        if bucket is None:
            continue  # sous le seuil effectif -> conforme, pas liste

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
