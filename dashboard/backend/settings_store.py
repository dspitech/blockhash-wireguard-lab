#!/usr/bin/env python3
"""
BLOCKHash - settings_store.py
=========================================================
Reglages ajustables depuis le dashboard, persistes dans un fichier
JSON (pas besoin de redemarrer le service pour qu'un changement soit
pris en compte, contrairement aux variables de /etc/blockhash/dashboard.env).

Ne contient QUE des reglages non sensibles (aucun secret ici) : les
identifiants de notification (SMTP, webhooks, bot Telegram) vivent
dans alerts.py / alerts-config.json, avec un mecanisme de masquage
dedie (voir alerts.py:mask_config).
"""

import json
import os
from pathlib import Path
from threading import Lock

SETTINGS_PATH = Path(os.environ.get("SETTINGS_PATH", "/etc/blockhash/dashboard-settings.json"))

DEFAULTS = {
    # Duree (s) sous laquelle un peer est considere "en ligne" depuis son dernier handshake.
    "online_threshold_sec": 180,
}

_lock = Lock()


def get_settings():
    data = dict(DEFAULTS)
    if SETTINGS_PATH.exists():
        try:
            data.update(json.loads(SETTINGS_PATH.read_text()))
        except (json.JSONDecodeError, OSError):
            pass  # fichier corrompu/illisible -> on retombe sur les defauts plutot que de planter l'API
    return data


def update_settings(partial):
    """Fusionne partiel dans le fichier existant (creation si absent), en ne
    conservant que les cles connues de DEFAULTS pour eviter d'accumuler des
    reglages fantomes via une requete malformee."""
    with _lock:
        current = get_settings()
        for key, value in partial.items():
            if key not in DEFAULTS:
                continue
            current[key] = value

        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(current, indent=2))
        tmp.replace(SETTINGS_PATH)
        return current


if __name__ == "__main__":
    print(json.dumps(get_settings(), indent=2))
