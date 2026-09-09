#!/usr/bin/env python3
"""
BLOCKHash - geoip.py
=========================================================
Resolution IP -> position geographique approximative, pour la carte des
endpoints clients (onglet Monitoring, voir README 7.10.5).

Utilise l'API gratuite ip-api.com (pas de cle requise, 45 requetes/minute
en usage non commercial, HTTP uniquement sur le plan gratuit - voir
https://ip-api.com/docs). Les resultats sont mis en cache dans la base
SQLite de store.py (table `geoip_cache`, TTL 7 jours par defaut) pour
rester tres largement sous cette limite meme avec de nombreux clients.

Aucune IP privee/reservee n'est jamais envoyee a l'API externe (RFC1918,
loopback, etc.) - ces endpoints ne peuvent de toute facon pas etre
geolocalises et resteraient simplement absents de la carte.
"""

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone

import store

GEOIP_API_URL = "http://ip-api.com/batch"
GEOIP_TTL_SEC = int(os.environ.get("GEOIP_TTL_SEC", str(7 * 86400)))
GEOIP_BATCH_MAX = 100  # limite documentee de l'API ip-api.com

_PRIVATE_IP_RE = re.compile(
    r"^(10\.|127\.|169\.254\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|0\.|::1$|f[cd][0-9a-f]{2}:)"
)


def _extract_ip(endpoint):
    """"1.2.3.4:51820" -> "1.2.3.4" ; "[::1]:51820" -> "::1" ; None si absent."""
    if not endpoint or endpoint == "(none)":
        return None
    if endpoint.startswith("["):
        return endpoint[1:].split("]")[0]
    return endpoint.rsplit(":", 1)[0]


def is_public_ip(ip):
    return bool(ip) and not _PRIVATE_IP_RE.match(ip)


def _fetch_batch(ips):
    """Un seul appel HTTP pour jusqu'a GEOIP_BATCH_MAX IP (voir doc ip-api.com
    /batch). Renvoie une liste de dicts alignee avec `ips`, ou une liste vide
    en cas d'echec reseau (jamais d'exception propagee - la carte doit rester
    utilisable meme si le service externe est injoignable)."""
    if not ips:
        return []
    payload = json.dumps([{"query": ip, "fields": "status,lat,lon,city,country,query"} for ip in ips]).encode()
    req = urllib.request.Request(GEOIP_API_URL, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return []


def resolve_ips(ips):
    """ips: iterable d'adresses IP (deja extraites, sans port). Renvoie un
    dict ip -> {"lat","lon","city","country"} pour les IP publiques
    resolues avec succes (les IP privees et les echecs de resolution sont
    simplement absents du dict, pas d'entree null)."""
    unique_ips = sorted({ip for ip in ips if is_public_ip(ip)})
    if not unique_ips:
        return {}

    now = int(datetime.now(tz=timezone.utc).timestamp())
    results = {}
    to_fetch = []

    for ip in unique_ips:
        cached = store.geoip_cache_get(ip)
        if cached and (now - cached["cached_ts"]) < GEOIP_TTL_SEC:
            if cached["lat"] is not None:
                results[ip] = {"lat": cached["lat"], "lon": cached["lon"], "city": cached["city"], "country": cached["country"]}
        else:
            to_fetch.append(ip)

    for batch_start in range(0, len(to_fetch), GEOIP_BATCH_MAX):
        batch = to_fetch[batch_start : batch_start + GEOIP_BATCH_MAX]
        for entry in _fetch_batch(batch):
            ip = entry.get("query")
            if not ip:
                continue
            if entry.get("status") == "success":
                store.geoip_cache_set(ip, entry.get("lat"), entry.get("lon"), entry.get("city"), entry.get("country"), now=now)
                results[ip] = {"lat": entry["lat"], "lon": entry["lon"], "city": entry.get("city"), "country": entry.get("country")}
            else:
                # echec de resolution (IP invalide, etc.) : on cache quand meme
                # une entree "vide" pour eviter de re-essayer a chaque appel
                store.geoip_cache_set(ip, None, None, None, None, now=now)

    return results


def resolve_endpoints(peers):
    """peers : liste de dicts issus de wgstate.load_live_peers(). Renvoie
    une liste prete pour la carte : un point par client dont l'endpoint
    est une IP publique resolue avec succes."""
    ip_by_pubkey = {p["public_key"]: _extract_ip(p.get("endpoint")) for p in peers}
    geo = resolve_ips(ip for ip in ip_by_pubkey.values() if ip)

    points = []
    for p in peers:
        ip = ip_by_pubkey.get(p["public_key"])
        loc = geo.get(ip) if ip else None
        if loc:
            points.append(
                {
                    "name": p["name"],
                    "status": p["status"],
                    "ip": ip,
                    "lat": loc["lat"],
                    "lon": loc["lon"],
                    "city": loc["city"],
                    "country": loc["country"],
                }
            )
    return points
