#!/usr/bin/env python3
"""
BLOCKHash - system_monitor.py
=========================================================
Supervision de la machine hote (CPU/RAM/disque/reseau) et des unites
systemd critiques du LAB. Ne necessite aucun privilege particulier :
`psutil` lit /proc, et `systemctl is-active` est autorise a n'importe
quel utilisateur par la politique polkit par defaut de systemd (lecture
seule de l'etat d'une unite, pas de droit d'action dessus).
"""

import os
import shutil
import subprocess
import time
from datetime import datetime, timezone

try:
    import psutil
except ImportError:  # pragma: no cover - degrade proprement si psutil n'est pas installe
    psutil = None

MONITORED_SERVICES = ["wg-quick@wg0", "blockhash-dashboard"]

_last_cpu_sample_ts = 0.0


def service_status(unit):
    try:
        result = subprocess.run(
            ["systemctl", "is-active", unit], capture_output=True, text=True, timeout=3
        )
        return result.stdout.strip() or "unknown"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "unknown"


def snapshot():
    global _last_cpu_sample_ts

    data = {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "psutil_available": psutil is not None,
        "services": {unit: service_status(unit) for unit in MONITORED_SERVICES},
    }

    if psutil is None:
        return data

    # cpu_percent(interval=None) donne l'ecart depuis le dernier appel : au tout
    # premier appel du process (juste apres le demarrage de gunicorn) la valeur
    # est peu fiable (0.0) -> on le signale plutot que d'afficher un chiffre faux.
    cpu_percent = psutil.cpu_percent(interval=None)
    first_call = _last_cpu_sample_ts == 0.0
    _last_cpu_sample_ts = time.time()

    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    net = psutil.net_io_counters()
    boot_ts = psutil.boot_time()

    data.update(
        {
            "cpu_percent": None if first_call else cpu_percent,
            "cpu_count": psutil.cpu_count(logical=True),
            "load_avg": list(os.getloadavg()) if hasattr(os, "getloadavg") else None,
            "memory": {
                "total_bytes": mem.total,
                "used_bytes": mem.used,
                "percent": mem.percent,
            },
            "disk": {
                "total_bytes": disk.total,
                "used_bytes": disk.used,
                "percent": disk.percent,
            },
            "net_io": {
                "bytes_recv": net.bytes_recv,
                "bytes_sent": net.bytes_sent,
            },
            "uptime_seconds": int(time.time() - boot_ts),
        }
    )
    return data


if __name__ == "__main__":
    import json

    print(json.dumps(snapshot(), indent=2))
