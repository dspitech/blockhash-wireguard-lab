#!/usr/bin/env python3
"""
BLOCKHash - anomalies.py
=========================================================
Detection d'anomalies simples, volontairement peu sophistiquee (LAB
pedagogique, pas un IDS) :

  - "traffic_spike"      : le debit du dernier bucket (24h/heure) d'un
                            pair depasse largement sa moyenne recente
                            (voir store.detect_traffic_spike).
  - "endpoint_flapping"   : le pair change d'IP endpoint anormalement
                            souvent sur les dernieres 24h (heuristique
                            deja calculee par app.py:build_reconnect_stats
                            a partir du CSV) - peut indiquer une cle
                            privee partagee/copiee sur plusieurs appareils.

Ce module ne fait AUCUN appel reseau/privilegie : il combine des
donnees deja calculees ailleurs (store.py pour le debit, le CSV de
logs pour les reconnexions).
"""

FLAPPING_RECONNECT_THRESHOLD = 6  # reconnexions/24h au-dela desquelles on signale


def detect_for_peer(pubkey, name, reconnect_count_24h, store_module):
    findings = []

    spike = store_module.detect_traffic_spike(pubkey, range_key="24h")
    if spike:
        findings.append(
            {
                "type": "traffic_spike",
                "peer": name,
                "severity": "warning",
                "message": (
                    f"Pic de trafic inhabituel sur « {name} » : "
                    f"{spike['last'] / 1_000_000:.1f} Mo sur le dernier intervalle "
                    f"contre une moyenne récente de {spike['mean'] / 1_000_000:.1f} Mo."
                ),
            }
        )

    if reconnect_count_24h is not None and reconnect_count_24h > FLAPPING_RECONNECT_THRESHOLD:
        findings.append(
            {
                "type": "endpoint_flapping",
                "peer": name,
                "severity": "warning",
                "message": (
                    f"« {name} » a changé d'endpoint {reconnect_count_24h} fois sur les "
                    "dernières 24h - vérifiez qu'il ne s'agit pas d'une clé partagée "
                    "entre plusieurs appareils."
                ),
            }
        )

    return findings


def detect_all(peers, reconnect_counts_by_pubkey, store_module):
    """peers : liste de dicts issus de load_live_peers() (name, public_key, enabled).
    reconnect_counts_by_pubkey : dict pubkey -> reconnect_count (24h), deja calcule
    par l'appelant (app.py) a partir du CSV pour eviter de le relire ici."""
    findings = []
    for peer in peers:
        if not peer.get("enabled", True):
            continue
        findings.extend(
            detect_for_peer(
                peer["public_key"],
                peer["name"],
                reconnect_counts_by_pubkey.get(peer["public_key"]),
                store_module,
            )
        )
    return findings
