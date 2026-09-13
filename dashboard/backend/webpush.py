# -*- coding: utf-8 -*-
"""Web Push (item 55) : vraies notifications navigateur, y compris onglet
fermé, via un service worker + VAPID - contrairement aux notifications
"desktop" (Notification API basique, tant que l'onglet reste ouvert) deja
presentes cote frontend.

Ce module :
- Génère et persiste une paire de clés VAPID (une fois, au premier appel).
- Fournit la clé publique (format brut base64url, celui attendu par
  `PushManager.subscribe({applicationServerKey: ...})` côté navigateur).
- Envoie une notification à tous les abonnements enregistrés, en supprimant
  automatiquement ceux qui sont expirés/révoqués (réponse HTTP 404/410 du
  service de push du navigateur).

Ne dépend d'aucun service tiers payant : le protocole Web Push standard
passe directement par le "push service" du navigateur de l'utilisateur
(Mozilla, Google, etc.), gratuit et sans compte à créer.
"""
import json
import os
from pathlib import Path

from py_vapid import Vapid
from pywebpush import WebPushException, webpush

VAPID_DIR = Path(os.environ.get("BLOCKHASH_CONFIG_DIR", "/etc/blockhash"))
VAPID_PRIVATE_KEY_PATH = VAPID_DIR / "vapid_private_key.pem"
VAPID_CLAIMS_SUB = os.environ.get("VAPID_CONTACT_EMAIL", "mailto:admin@example.com")

_cached_vapid = None


def _load_or_create_vapid():
    """Charge la paire de clés VAPID existante, ou en génère une nouvelle au
    tout premier appel (fichier privé, permissions restrictives)."""
    global _cached_vapid
    if _cached_vapid is not None:
        return _cached_vapid

    if VAPID_PRIVATE_KEY_PATH.exists():
        vapid = Vapid.from_file(str(VAPID_PRIVATE_KEY_PATH))
    else:
        VAPID_DIR.mkdir(parents=True, exist_ok=True)
        vapid = Vapid()
        vapid.generate_keys()
        vapid.save_key(str(VAPID_PRIVATE_KEY_PATH))
        os.chmod(VAPID_PRIVATE_KEY_PATH, 0o600)

    _cached_vapid = vapid
    return vapid


def public_key_b64url():
    """Clé publique VAPID au format brut (point EC non compressé, 65 octets)
    encodé en base64url sans padding - c'est exactement ce que
    `Uint8Array` + `applicationServerKey` attendent côté navigateur."""
    import base64
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    vapid = _load_or_create_vapid()
    raw = vapid.public_key.public_bytes(
        encoding=Encoding.X962, format=PublicFormat.UncompressedPoint
    )
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def send_to_subscription(subscription_info, title, body, url="/"):
    """Envoie une notification à UN abonnement. Lève WebPushException si le
    service de push du navigateur refuse (l'appelant décide quoi faire d'une
    éventuelle expiration - voir broadcast() ci-dessous pour le cas courant)."""
    vapid = _load_or_create_vapid()
    payload = json.dumps({"title": title, "body": body, "url": url})
    webpush(
        subscription_info=subscription_info,
        data=payload,
        vapid_private_key=str(VAPID_PRIVATE_KEY_PATH),
        vapid_claims={"sub": VAPID_CLAIMS_SUB},
    )


def broadcast(title, body, url="/"):
    """Envoie à tous les abonnements connus (voir store.list_push_subscriptions),
    purge silencieusement ceux qui ne sont plus valides (410 Gone / 404), et
    ne lève jamais - une notification ratée ne doit pas casser le flux
    d'alerte appelant (même politique que les autres canaux, voir alerts.py)."""
    import store  # import différé : évite un cycle store<->webpush au chargement

    sent, expired = 0, 0
    for sub in store.list_push_subscriptions():
        subscription_info = {
            "endpoint": sub["endpoint"],
            "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
        }
        try:
            send_to_subscription(subscription_info, title, body, url=url)
            sent += 1
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in (404, 410):
                store.delete_push_subscription(sub["endpoint"])
                expired += 1
            # autres erreurs (delai reseau, cle mal formee) : on n'insiste pas,
            # ce n'est pas la responsabilite de dispatch() de faire du retry.
        except Exception:
            pass
    return {"sent": sent, "expired_removed": expired}
