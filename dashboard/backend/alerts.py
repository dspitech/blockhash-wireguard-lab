#!/usr/bin/env python3
"""
BLOCKHash - alerts.py
=========================================================
Moteur d'alertes configurable. Deux usages :

  1) Bibliotheque importee par app.py pour exposer /api/alerts/*
     (lecture/ecriture de la config avec masquage des secrets, envoi
     d'une notification de test, historique) ;
  2) Script CLI (`python3 alerts.py check`) invoque par
     scripts/09-check-alerts.sh (cron, toutes les 5 minutes, en root)
     pour evaluer les regles et notifier les canaux configures.

Contrairement a wgctl.py, ce module N'A PAS BESOIN de privileges root
pour l'evaluation des regles elles-memes (lecture de wg0.conf, `wg
show` deja autorise par la regle sudoers de lecture, et la base
SQLite de store.py) - root n'est necessaire que parce que le cron
systeme (crontab racine) est le mecanisme le plus simple pour un LAB.
Rien n'empeche de le lancer sous un compte moins privilegie qui a
uniquement acces en lecture a /etc/wireguard et /var/log/wireguard.

Configuration : /etc/blockhash/alerts-config.json (secrets inclus,
fichier chmod 600 proprietaire www-data - voir 03-install-dashboard.sh
et la section 7.7.4 du README). Les valeurs sensibles ne sont JAMAIS
renvoyees en clair par GET /api/alerts/config (voir `mask_config` /
MASK) : le frontend affiche un marqueur "deja configure" et n'envoie
la vraie valeur que lorsqu'elle change.
"""

import argparse
import copy
import json
import os
import smtplib
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path

import store
import system_monitor
from wgstate import load_live_peers, reconnect_counts_last_24h
try:
    import webpush
    WEBPUSH_AVAILABLE = True
except ImportError:
    webpush = None
    WEBPUSH_AVAILABLE = False

CONFIG_PATH = Path(os.environ.get("ALERTS_CONFIG_PATH", "/etc/blockhash/alerts-config.json"))
MASK = "••••••••"
SECRET_PATHS = [
    ("channels", "email", "smtp_password"),
    ("channels", "slack_webhook_url"),
    ("channels", "discord_webhook_url"),
    ("channels", "telegram", "bot_token"),
]

DEFAULT_CONFIG = {
    "enabled": False,
    "rules": {
        "inactive_days": 7,          # null/0 pour desactiver la regle
        "bandwidth_alert_mb_5min": None,
        "service_down": True,
        "connect_disconnect": True,  # alerte a chaque connexion/deconnexion d'un client
        "off_hours": {"enabled": False, "start": "22:00", "end": "06:00"},  # connexion hors plage horaire
        "failed_auth_attempts": True,   # alerte quand le verrouillage anti-bruteforce du login se declenche
        "client_expiry_days": 3,     # alerte N jours avant la date d'expiration d'un client (0/null desactive)
        "new_ip": True,              # alerte si un client se connecte depuis une IP jamais vue pour lui
        "cpu_percent_threshold": None,   # ex. 90 -> alerte si CPU > 90%
        "disk_percent_threshold": None,  # ex. 90 -> alerte si disque > 90%
    },
    "cooldowns_sec": {
        "inactive": 86400,     # 1 alerte par client inactif et par jour max
        "bandwidth": 3600,     # 1 alerte par client et par heure max
        "service_down": 1800,  # 1 alerte tous les 30 min tant que le service est down
        "connect_disconnect": 60,  # evite les doublons entre onglets/workers sur la meme transition
        "off_hours": 60,
        "failed_auth_attempts": 300,
        "client_expiry": 86400,
        "new_ip": 300,
        "cpu_threshold": 1800,
        "disk_threshold": 3600,
    },
    "max_alerts_per_hour": 0,  # 0 = illimite ; au-dela, les nouvelles alertes sont journalisees mais pas notifiees
    "channels": {
        "email": {
            "enabled": False,
            "smtp_host": "",
            "smtp_port": 587,
            "smtp_user": "",
            "smtp_password": "",
            "use_tls": True,
            "from_addr": "",
            "to_addr": "",
        },
        "slack_webhook_url": "",
        "slack_enabled": True,     # desactivation temporaire sans effacer l'URL configuree
        "discord_webhook_url": "",
        "discord_enabled": True,
        "telegram": {"bot_token": "", "chat_id": "", "enabled": True},
        "webpush_enabled": True,
        "webpush_min_level": "critical",  # "info" | "warning" | "critical" : niveau minimal envoye en Web Push
    },
}


# ---------------------------------------------------------------------
# Chargement / sauvegarde avec masquage des secrets
# ---------------------------------------------------------------------
def _get_path(d, path):
    for key in path:
        d = d.get(key, {}) if isinstance(d, dict) else {}
    return d if not isinstance(d, dict) else None


def _set_path(d, path, value):
    for key in path[:-1]:
        d = d.setdefault(key, {})
    d[path[-1]] = value


def load_config():
    config = copy.deepcopy(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            stored = json.loads(CONFIG_PATH.read_text())
            _deep_merge(config, stored)
        except (json.JSONDecodeError, OSError):
            pass
    return config


def _deep_merge(base, override):
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def mask_config(config):
    """Copie la config en remplacant chaque secret non vide par MASK,
    pour l'affichage cote dashboard (jamais le secret en clair)."""
    masked = copy.deepcopy(config)
    for path in SECRET_PATHS:
        value = _get_path(masked, path)
        if value:
            _set_path(masked, path, MASK)
    return masked


def save_config(partial):
    """Fusionne `partial` (potentiellement avec des valeurs MASK a ignorer,
    envoyees par un formulaire qui n'a pas touche au champ secret) dans la
    config existante, puis ecrit sur disque de facon atomique."""
    current = load_config()

    def merge_with_mask(base, override):
        for key, value in override.items():
            if isinstance(value, dict) and isinstance(base.get(key), dict):
                merge_with_mask(base[key], value)
            elif value == MASK:
                continue  # champ secret non modifie par l'utilisateur -> on garde l'existant
            else:
                base[key] = value

    merge_with_mask(current, partial)

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(current, indent=2))
    os.chmod(tmp, 0o600)
    tmp.replace(CONFIG_PATH)
    return current


# ---------------------------------------------------------------------
# Envoi de notifications (best effort, une erreur sur un canal ne doit
# jamais faire echouer les autres)
# ---------------------------------------------------------------------
def _post_webhook(url, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status < 400


def send_slack(webhook_url, message):
    return _post_webhook(webhook_url, {"text": message})


def send_discord(webhook_url, message):
    return _post_webhook(webhook_url, {"content": message})


def send_telegram(bot_token, chat_id, message):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": message}).encode()
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status < 400


def send_email(email_cfg, subject, message):
    msg = MIMEText(message)
    msg["Subject"] = subject
    msg["From"] = email_cfg["from_addr"]
    msg["To"] = email_cfg["to_addr"]

    with smtplib.SMTP(email_cfg["smtp_host"], int(email_cfg["smtp_port"]), timeout=10) as smtp:
        if email_cfg.get("use_tls", True):
            smtp.starttls()
        if email_cfg.get("smtp_user"):
            smtp.login(email_cfg["smtp_user"], email_cfg["smtp_password"])
        smtp.sendmail(email_cfg["from_addr"], [email_cfg["to_addr"]], msg.as_string())
    return True


def dispatch(config, subject, message, level="warning", rule_key=None, peer_name=None):
    """Envoie `message` sur tous les canaux actifs. Renvoie la liste des
    canaux ayant reussi (utilisee pour l'historique, voir store.insert_alert).
    Si `max_alerts_per_hour` est depasse, l'alerte est journalisee (visible
    dans l'historique) mais AUCUNE notification n'est envoyee - evite les
    tempetes de notifications tout en gardant une trace complete."""
    max_per_hour = config.get("max_alerts_per_hour") or 0
    throttled = max_per_hour > 0 and store.count_alerts_last_hour() >= max_per_hour

    channels_ok = []
    ch = config["channels"]

    if not throttled:
        if ch["email"]["enabled"] and ch["email"].get("smtp_host"):
            try:
                send_email(ch["email"], subject, message)
                channels_ok.append("email")
            except Exception as exc:  # best effort : ne bloque jamais les autres canaux
                print(f"[alerts] email KO : {exc}", file=sys.stderr)

        if ch.get("slack_enabled", True) and ch.get("slack_webhook_url"):
            try:
                send_slack(ch["slack_webhook_url"], message)
                channels_ok.append("slack")
            except Exception as exc:
                print(f"[alerts] slack KO : {exc}", file=sys.stderr)

        if ch.get("discord_enabled", True) and ch.get("discord_webhook_url"):
            try:
                send_discord(ch["discord_webhook_url"], message)
                channels_ok.append("discord")
            except Exception as exc:
                print(f"[alerts] discord KO : {exc}", file=sys.stderr)

        telegram = ch.get("telegram", {})
        if telegram.get("enabled", True) and telegram.get("bot_token") and telegram.get("chat_id"):
            try:
                send_telegram(telegram["bot_token"], telegram["chat_id"], message)
                channels_ok.append("telegram")
            except Exception as exc:
                print(f"[alerts] telegram KO : {exc}", file=sys.stderr)

        levels_order = {"info": 0, "warning": 1, "critical": 2}
        min_level = ch.get("webpush_min_level", "critical")
        if (
            WEBPUSH_AVAILABLE
            and ch.get("webpush_enabled", True)
            and levels_order.get(level, 0) >= levels_order.get(min_level, 2)
        ):
            try:
                webpush.broadcast(subject, message)
                channels_ok.append("webpush")
            except Exception as exc:
                print(f"[alerts] webpush KO : {exc}", file=sys.stderr)

    store.insert_alert(
        level, subject, message + (" [notification throttlee : quota horaire atteint]" if throttled else ""),
        channels=channels_ok, rule_key=rule_key, peer_name=peer_name,
    )
    return channels_ok


def send_test(channel):
    """Envoie un message de test sur UN canal precis (bouton "Tester" du dashboard)."""
    config = load_config()
    message = "Ceci est une notification de test envoyee depuis le dashboard BLOCKHash."
    ch = config["channels"]

    if channel == "email":
        send_email(ch["email"], "BLOCKHash - Test de notification", message)
    elif channel == "slack":
        send_slack(ch["slack_webhook_url"], message)
    elif channel == "discord":
        send_discord(ch["discord_webhook_url"], message)
    elif channel == "telegram":
        send_telegram(ch["telegram"]["bot_token"], ch["telegram"]["chat_id"], message)
    else:
        raise ValueError(f"Canal inconnu : {channel}")
    return True


# ---------------------------------------------------------------------
# Evaluation des regles (appelee par le cron, voir scripts/09-check-alerts.sh)
# ---------------------------------------------------------------------
def evaluate_rules(config=None, now=None):
    config = config or load_config()
    if not config.get("enabled"):
        return {"checked": False, "reason": "alerting desactive"}

    now = now if now is not None else datetime.now(tz=timezone.utc)
    now_ts = int(now.timestamp())
    rules = config["rules"]
    cooldowns = config["cooldowns_sec"]
    triggered = []

    peers = load_live_peers()

    # -- Regle 1 : inactivite prolongee --------------------------------
    inactive_days = rules.get("inactive_days")
    if inactive_days:
        threshold_sec = inactive_days * 86400
        for peer in peers:
            if not peer["enabled"]:
                continue
            since = peer.get("seconds_since_handshake")
            never_connected = since is None
            if never_connected or since > threshold_sec:
                rule_key = f"inactive:{peer['public_key']}"
                if store.should_send(rule_key, cooldowns.get("inactive", 86400), now=now_ts):
                    msg = (
                        f"Client « {peer['name']} » "
                        + (
                            "ne s'est jamais connecté."
                            if never_connected
                            else f"inactif depuis plus de {inactive_days} jour(s)."
                        )
                    )
                    channels = dispatch(config, "BLOCKHash - Client inactif", msg, level="warning", rule_key=rule_key, peer_name=peer["name"])
                    triggered.append({"rule": "inactive_days", "peer": peer["name"], "channels": channels})

    # -- Regle 2 : seuil de bande passante (dernier intervalle 5 min) --
    bw_threshold_mb = rules.get("bandwidth_alert_mb_5min")
    if bw_threshold_mb:
        threshold_bytes = bw_threshold_mb * 1_000_000
        for peer in peers:
            if not peer["enabled"]:
                continue
            bucket = store.latest_bucket_totals(peer["public_key"], now=now_ts)
            total = bucket["rx"] + bucket["tx"]
            if total > threshold_bytes:
                rule_key = f"bandwidth:{peer['public_key']}"
                if store.should_send(rule_key, cooldowns.get("bandwidth", 3600), now=now_ts):
                    msg = (
                        f"Client « {peer['name']} » a dépassé le seuil de bande passante : "
                        f"{total / 1_000_000:.1f} Mo sur le dernier intervalle "
                        f"(seuil {bw_threshold_mb} Mo)."
                    )
                    channels = dispatch(config, "BLOCKHash - Seuil de débit dépassé", msg, level="warning", rule_key=rule_key, peer_name=peer["name"])
                    triggered.append({"rule": "bandwidth", "peer": peer["name"], "channels": channels})

    # -- Regle 3 : service WireGuard/dashboard hors ligne --------------
    if rules.get("service_down"):
        statuses = {unit: system_monitor.service_status(unit) for unit in system_monitor.MONITORED_SERVICES}
        for unit, status in statuses.items():
            if status not in ("active",):
                rule_key = f"service_down:{unit}"
                if store.should_send(rule_key, cooldowns.get("service_down", 1800), now=now_ts):
                    msg = f"Le service « {unit} » n'est pas actif (statut : {status})."
                    channels = dispatch(config, "BLOCKHash - Service hors ligne", msg, level="critical", rule_key=rule_key, peer_name=None)
                    triggered.append({"rule": "service_down", "peer": unit, "channels": channels})

    # -- Regle 3bis : seuils systeme (CPU / disque) --------------------
    cpu_threshold = rules.get("cpu_percent_threshold")
    disk_threshold = rules.get("disk_percent_threshold")
    if cpu_threshold or disk_threshold:
        snap = system_monitor.snapshot()
        if cpu_threshold and snap.get("cpu_percent") is not None and snap["cpu_percent"] > cpu_threshold:
            rule_key = "cpu_threshold"
            if store.should_send(rule_key, cooldowns.get("cpu_threshold", 1800), now=now_ts):
                msg = f"CPU à {snap['cpu_percent']:.0f}% (seuil configuré : {cpu_threshold}%)."
                channels = dispatch(config, "BLOCKHash - Charge CPU élevée", msg, level="warning", rule_key=rule_key)
                triggered.append({"rule": "cpu_percent_threshold", "peer": None, "channels": channels})
        if disk_threshold and snap.get("disk", {}).get("percent") is not None and snap["disk"]["percent"] > disk_threshold:
            rule_key = "disk_threshold"
            if store.should_send(rule_key, cooldowns.get("disk_threshold", 3600), now=now_ts):
                msg = f"Disque à {snap['disk']['percent']:.0f}% d'occupation (seuil configuré : {disk_threshold}%)."
                channels = dispatch(config, "BLOCKHash - Espace disque critique", msg, level="critical", rule_key=rule_key)
                triggered.append({"rule": "disk_percent_threshold", "peer": None, "channels": channels})

    # -- Regle 4 : expiration de client proche -------------------------
    expiry_days = rules.get("client_expiry_days")
    if expiry_days:
        for peer in peers:
            if not peer["enabled"] or not peer.get("expires"):
                continue
            try:
                expires_date = datetime.fromisoformat(peer["expires"]).date()
            except ValueError:
                continue
            days_left = (expires_date - now.date()).days
            if 0 <= days_left <= expiry_days:
                rule_key = f"client_expiry:{peer['public_key']}:{expires_date.isoformat()}"
                if store.should_send(rule_key, cooldowns.get("client_expiry", 86400), now=now_ts):
                    msg = f"Client « {peer['name']} » expire le {expires_date.isoformat()} (dans {days_left} jour(s))."
                    channels = dispatch(config, "BLOCKHash - Expiration proche", msg, level="warning", rule_key=rule_key, peer_name=peer["name"])
                    triggered.append({"rule": "client_expiry_days", "peer": peer["name"], "channels": channels})

    # -- Regle 5 : connexion depuis une IP jamais vue pour ce client ---
    if rules.get("new_ip"):
        for peer in peers:
            if not peer["enabled"] or not peer.get("endpoint"):
                continue
            current_ip = peer["endpoint"].rsplit(":", 1)[0].strip("[]")
            last = store.get_peer_last_ip(peer["public_key"])
            if last and last.get("endpoint_ip") and last["endpoint_ip"] != current_ip:
                rule_key = f"new_ip:{peer['public_key']}:{current_ip}"
                if store.should_send(rule_key, cooldowns.get("new_ip", 300), now=now_ts):
                    msg = f"Client « {peer['name']} » s'est connecté depuis une nouvelle IP : {current_ip} (précédente : {last['endpoint_ip']})."
                    channels = dispatch(config, "BLOCKHash - Nouvelle IP détectée", msg, level="warning", rule_key=rule_key, peer_name=peer["name"])
                    triggered.append({"rule": "new_ip", "peer": peer["name"], "channels": channels})
            store.set_peer_last_ip(peer["public_key"], current_ip, ts=now_ts)

    return {"checked": True, "triggered": triggered}


def main():
    parser = argparse.ArgumentParser(description="BLOCKHash - alerts.py")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("check", help="Evalue les regles et notifie si necessaire")
    p_test = sub.add_parser("test", help="Envoie une notification de test")
    p_test.add_argument("channel", choices=["email", "slack", "discord", "telegram"])

    args = parser.parse_args()
    if args.action == "check":
        result = evaluate_rules()
        print(json.dumps(result))
    elif args.action == "test":
        send_test(args.channel)
        print(json.dumps({"ok": True}))


if __name__ == "__main__":
    main()
