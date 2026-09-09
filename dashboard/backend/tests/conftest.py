"""
BLOCKHash - conftest.py
=========================================================
Fixtures partagees par tous les tests. Chaque test recoit un
environnement ENTIEREMENT isole (repertoire temporaire, variables
d'environnement dediees) : aucun test ne touche jamais /etc/wireguard,
/var/log/wireguard ou /etc/blockhash du systeme reel.

Le pattern reproduit exactement ce qui a ete verifie manuellement tout
au long du developpement (voir README section 12) : un faux binaire
`wg` sous $PATH, un `wg0.conf` minimal, des chemins de base de
donnees/configuration pointant vers le repertoire temporaire.
"""

import importlib
import os
import stat
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture
def wg_env(tmp_path, monkeypatch):
    """Cree une arborescence /etc/wireguard-like sous tmp_path, un faux
    binaire `wg` minimal, et positionne toutes les variables d'env que
    lisent wgstate.py/store.py/app.py. Renvoie le dict de chemins utiles."""
    wg_dir = tmp_path / "wireguard"
    (wg_dir / "clients").mkdir(parents=True)
    blockhash_dir = tmp_path / "blockhash"
    blockhash_dir.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    wg_conf = wg_dir / "wg0.conf"
    wg_conf.write_text(
        "[Interface]\n"
        "Address = 10.66.66.1/24\n"
        "ListenPort = 51820\n"
        "PrivateKey = SERVERPRIVKEY0000000000000000000000000000=\n"
    )

    fake_wg = bin_dir / "wg"
    fake_wg.write_text("#!/usr/bin/env bash\n[ \"$1\" = \"show\" ] && echo \"wg0\"\nexit 0\n")
    fake_wg.chmod(fake_wg.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("WG_DIR", str(wg_dir))
    monkeypatch.setenv("WG_CONF_PATH", str(wg_conf))
    monkeypatch.setenv("WG_LOG_CSV", str(tmp_path / "tunnels.csv"))
    monkeypatch.setenv("METRICS_DB_PATH", str(tmp_path / "blockhash.db"))
    monkeypatch.setenv("METRICS_DB_GROUP", "nogroup")
    monkeypatch.setenv("SETTINGS_PATH", str(blockhash_dir / "settings.json"))
    monkeypatch.setenv("ALERTS_CONFIG_PATH", str(blockhash_dir / "alerts.json"))
    monkeypatch.setenv("REPORTS_CONFIG_PATH", str(blockhash_dir / "reports.json"))
    monkeypatch.setenv("SERVERS_CONFIG_PATH", str(blockhash_dir / "servers.json"))
    monkeypatch.setenv("WG_EXPORT_DIR", str(tmp_path / "exports"))
    monkeypatch.setenv("CLIENT_MANAGEMENT_ENABLED", "false")
    monkeypatch.setenv("SYSTEM_OPS_ENABLED", "false")
    monkeypatch.setenv("DASHBOARD_TOKEN", "")

    return {
        "tmp_path": tmp_path,
        "wg_dir": wg_dir,
        "wg_conf": wg_conf,
        "bin_dir": bin_dir,
        "blockhash_dir": blockhash_dir,
    }


def add_peer(wg_conf_path, name, pubkey, allowed_ips, enabled=True, meta=None):
    """Ajoute un bloc [Peer] minimal a un wg0.conf de test (memes
    conventions que wgctl.py, voir dashboard/backend/wgctl.py)."""
    import json as _json

    meta = meta or {"created": "2026-01-01T00:00:00+00:00", "expires": None, "bw_up_mbit": None, "bw_down_mbit": None}
    lines = [
        "[Peer]",
        f"# Client : {name}",
        f"# Meta : {_json.dumps(meta)}",
        f"PublicKey = {pubkey}",
        f"AllowedIPs = {allowed_ips}",
    ]
    block = "\n".join(lines)
    if not enabled:
        block = "\n".join("#" + line for line in block.splitlines())
    with open(wg_conf_path, "a") as f:
        f.write("\n" + block + "\n")


@pytest.fixture
def fresh_modules():
    """Certains modules (wgstate, store, app...) lisent leurs constantes
    de configuration (chemins) UNE FOIS a l'import. Comme les fixtures
    monkeypatchent les variables d'environnement APRES le premier import
    fait par un test precedent, il faut recharger ces modules pour que
    les nouveaux chemins soient pris en compte a chaque test."""
    names = ["wgstate", "store", "settings_store", "alerts", "reports", "servers_store", "system_monitor", "app"]
    for name in list(sys.modules):
        if name in names:
            del sys.modules[name]
    yield
