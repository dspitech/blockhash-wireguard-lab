#!/usr/bin/env python3
"""
BLOCKHash - servers_store.py
=========================================================
Registre des AUTRES serveurs BLOCKHash a superviser depuis ce dashboard
(voir README 7.8.5 - "si le lab s'etend a plusieurs VM WireGuard").

Ce module ne stocke QUE des metadonnees de connexion (nom, URL de base,
jeton d'API) dans un fichier JSON local - aucune donnee du serveur
distant (clients, logs, metriques) n'est jamais persistee ici. Chaque
consultation de la vue "Multi-serveurs" declenche un appel HTTP a la
volee vers `/api/overview` du serveur distant, cote backend (pas depuis
le navigateur), pour eviter d'exposer les jetons d'API des serveurs
distants au client JavaScript.

Limite assumee : ceci est une supervision AGREGEE (KPI de chaque serveur
en un coup d'oeil), pas une federation complete - gerer les clients d'un
serveur distant se fait en ouvrant SON propre dashboard (lien direct),
pas depuis cette instance. Voir README 7.8.5 pour la discussion.
"""

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

SERVERS_PATH = Path(os.environ.get("SERVERS_CONFIG_PATH", "/etc/blockhash/servers.json"))
MASK = "••••••••"
NAME_MAX_LEN = 40


class ServerStoreError(Exception):
    pass


def _load_raw():
    if not SERVERS_PATH.exists():
        return []
    try:
        data = json.loads(SERVERS_PATH.read_text())
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_raw(servers):
    SERVERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SERVERS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(servers, indent=2))
    os.chmod(tmp, 0o600)
    tmp.replace(SERVERS_PATH)


def list_servers(masked=True):
    servers = _load_raw()
    if not masked:
        return servers
    return [
        {**s, "api_token": MASK if s.get("api_token") else ""}
        for s in servers
    ]


def add_server(name, base_url, api_token=""):
    name = (name or "").strip()
    base_url = (base_url or "").strip().rstrip("/")
    if not name or len(name) > NAME_MAX_LEN:
        raise ServerStoreError("Nom de serveur invalide (1-40 caractères).")
    if not base_url.startswith(("http://", "https://")):
        raise ServerStoreError("L'URL doit commencer par http:// ou https://.")

    servers = _load_raw()
    if any(s["name"].lower() == name.lower() for s in servers):
        raise ServerStoreError(f"Un serveur nommé « {name} » existe déjà.")

    servers.append({"name": name, "base_url": base_url, "api_token": api_token})
    _save_raw(servers)
    return list_servers()


def remove_server(name):
    servers = _load_raw()
    filtered = [s for s in servers if s["name"].lower() != (name or "").lower()]
    if len(filtered) == len(servers):
        raise ServerStoreError(f"Serveur inconnu : {name}")
    _save_raw(filtered)
    return list_servers()


def fetch_overview(name, timeout=6):
    """Recupere /api/overview du serveur distant nomme `name`. Renvoie
    toujours un dict {"ok": bool, ...} plutot que de lever, pour que
    l'appelant puisse afficher un statut "injoignable" par serveur sans
    que ça fasse echouer l'ensemble de la vue Multi-serveurs."""
    servers = _load_raw()
    server = next((s for s in servers if s["name"].lower() == (name or "").lower()), None)
    if not server:
        raise ServerStoreError(f"Serveur inconnu : {name}")

    url = server["base_url"] + "/api/overview"
    headers = {"X-API-Token": server.get("api_token", "")} if server.get("api_token") else {}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return {"ok": True, "name": name, "data": json.loads(resp.read().decode())}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "name": name, "error": f"HTTP {exc.code}"}
    except urllib.error.URLError as exc:
        return {"ok": False, "name": name, "error": str(exc.reason)}
    except Exception as exc:  # timeout, JSON invalide, etc.
        return {"ok": False, "name": name, "error": str(exc)}


def fetch_all_overviews(timeout=6):
    return [fetch_overview(s["name"], timeout=timeout) for s in _load_raw()]
