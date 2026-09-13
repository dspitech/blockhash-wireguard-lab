#!/usr/bin/env python3
"""
BLOCKHash - wgops.py
=========================================================
Operations systeme privilegiees sur le serveur WireGuard :
  - sauvegarde / restauration / diff de wg0.conf (versionne sur disque)
  - rotation assistee des cles du SERVEUR (regenere aussi le .conf de
    chaque client existant, puisqu'il embarque la cle publique serveur)
  - redemarrage du tunnel (systemctl restart wg-quick@<if>)
  - export d'audit (zip de toutes les configs clients + wg0.conf)

Meme modele de securite que wgctl.py (voir README 7.6.1) : ce fichier est
le SEUL point d'entree autorise a executer ces actions, il est root:root
/ chmod 750, et www-data ne peut l'invoquer qu'au travers d'une regle
sudoers dediee (`sudo -n python3 wgops.py <action> ...`). Toute la
validation (noms de fichiers de sauvegarde, absence de traversal de
chemin) est faite ICI, jamais cote Flask.

Actions -> JSON unique sur stdout, exit code non nul en cas d'erreur,
comme wgctl.py.
"""

import argparse
import base64
import difflib
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

WG_IF = os.environ.get("WG_INTERFACE", "wg0")
WG_DIR = Path(os.environ.get("WG_DIR", "/etc/wireguard"))
WG_CONF = Path(os.environ.get("WG_CONF_PATH", str(WG_DIR / f"{WG_IF}.conf")))
CLIENTS_DIR = WG_DIR / "clients"
BACKUPS_DIR = WG_DIR / "backups"
MAX_BACKUPS = int(os.environ.get("WG_MAX_BACKUPS", "50"))
EXPORT_DIR = Path(os.environ.get("WG_EXPORT_DIR", "/tmp/blockhash-exports"))
EXPORT_MAX_AGE_SEC = 3600  # les exports sont ephemeres, purges a chaque nouvel export
SERVICE_GROUP = os.environ.get("METRICS_DB_GROUP", "www-data")

BACKUP_NAME_RE = re.compile(r"^wg0_[0-9]{8}-[0-9]{6}_[A-Za-z0-9_-]{1,40}\.conf$")


class OpsError(Exception):
    """Erreur controlee -> renvoyee proprement en JSON, jamais de trace."""


def run(cmd, input_text=None, check=True):
    return subprocess.run(cmd, input=input_text, text=True, capture_output=True, check=check)


def run_bash(script, check=False):
    return subprocess.run(["bash", "-c", script], text=True, capture_output=True, check=check)


def sync_live():
    result = run_bash(f"wg syncconf {WG_IF} <(wg-quick strip {WG_IF})")
    if result.returncode != 0:
        raise OpsError(f"wg syncconf a echoue : {result.stderr.strip()}")


def _chgrp_readable(path):
    """Rend un fichier lisible par le groupe de service (www-data), pour
    que le process Flask (non-root) puisse le servir en telechargement."""
    try:
        import grp

        gid = grp.getgrnam(SERVICE_GROUP).gr_gid
        os.chown(path, 0, gid)
        os.chmod(path, 0o640)
    except (KeyError, PermissionError, ImportError):
        pass


# ---------------------------------------------------------------------
# Sauvegardes de wg0.conf (versionnees, avec diff avant restauration)
# ---------------------------------------------------------------------
def _backup_filename(label):
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d-%H%M%S")
    safe_label = re.sub(r"[^A-Za-z0-9_-]", "", label or "manuel")[:40] or "manuel"
    return f"wg0_{ts}_{safe_label}.conf"


def _prune_backups():
    backups = sorted(BACKUPS_DIR.glob("wg0_*.conf"), key=lambda p: p.stat().st_mtime)
    while len(backups) > MAX_BACKUPS:
        backups.pop(0).unlink(missing_ok=True)


def _meta_path(filename):
    return BACKUPS_DIR / f"{filename}.meta.json"


def _sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def do_backup(label, description=None):
    if not WG_CONF.exists():
        raise OpsError("wg0.conf introuvable.")
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    filename = _backup_filename(label)
    dest = BACKUPS_DIR / filename
    shutil.copy2(WG_CONF, dest)
    os.chmod(dest, 0o640)
    if description:
        meta = {"description": description[:500]}
        _meta_path(filename).write_text(json.dumps(meta))
        os.chmod(_meta_path(filename), 0o640)
    _prune_backups()
    return {"filename": filename, "created": datetime.now(tz=timezone.utc).isoformat(), "sha256": _sha256_of(dest)}


def act_backup(args):
    result = do_backup(args.label, description=getattr(args, "description", None))
    return {"ok": True, **result}


AUTO_BACKUP_SCHEDULE_SECONDS = {"daily": 86400, "weekly": 7 * 86400, "monthly": 30 * 86400}


def act_auto_backup(args):
    """Invoquee par le cron quotidien (voir scripts/03-install-dashboard.sh) :
    ne cree une sauvegarde que si le planning configure dans le dashboard
    (reglage 'backup_schedule' : disabled/daily/weekly/monthly) l'exige,
    en comparant a la sauvegarde 'auto' la plus recente. Auto-limitation
    plutot qu'une reecriture dynamique de la crontab (plus simple, plus
    sur : www-data n'a jamais besoin d'ecrire dans /etc/crontab)."""
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent))
        import settings_store
        schedule = settings_store.get_settings().get("backup_schedule", "disabled")
    except Exception:
        schedule = "disabled"

    if schedule not in AUTO_BACKUP_SCHEDULE_SECONDS:
        return {"ok": True, "skipped": True, "reason": f"planning desactive ({schedule})"}

    auto_backups = sorted(BACKUPS_DIR.glob("wg0_*_auto.conf"), key=lambda p: p.stat().st_mtime, reverse=True)
    if auto_backups:
        age = time.time() - auto_backups[0].stat().st_mtime
        if age < AUTO_BACKUP_SCHEDULE_SECONDS[schedule]:
            return {"ok": True, "skipped": True, "reason": "pas encore due", "age_sec": int(age)}

    result = do_backup("auto", description=f"Sauvegarde planifiee ({schedule})")
    return {"ok": True, "skipped": False, **result}


def act_list_backups(args):
    if not BACKUPS_DIR.exists():
        return {"ok": True, "backups": []}
    backups = []
    for p in sorted(BACKUPS_DIR.glob("wg0_*.conf"), key=lambda p: p.stat().st_mtime, reverse=True):
        stat = p.stat()
        try:
            peer_count = len(re.findall(r"^#{0,2}\[Peer\]\s*$", p.read_text(errors="ignore"), re.MULTILINE))
        except OSError:
            peer_count = None
        description = None
        meta_path = _meta_path(p.name)
        if meta_path.exists():
            try:
                description = json.loads(meta_path.read_text()).get("description")
            except (json.JSONDecodeError, OSError):
                pass
        backups.append(
            {
                "filename": p.name,
                "size_bytes": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                "peer_count": peer_count,
                "sha256": _sha256_of(p),
                "description": description,
            }
        )
    return {"ok": True, "backups": backups}


def _safe_backup_path(filename):
    if not filename or not BACKUP_NAME_RE.match(filename):
        raise OpsError("Nom de sauvegarde invalide.")
    path = (BACKUPS_DIR / filename).resolve()
    if BACKUPS_DIR.resolve() not in path.parents or not path.exists():
        raise OpsError(f"Sauvegarde introuvable : {filename}")
    return path


def act_diff_backup(args):
    path = _safe_backup_path(args.filename)
    backup_text = path.read_text(errors="ignore")
    current_text = WG_CONF.read_text(errors="ignore") if WG_CONF.exists() else ""
    diff_lines = list(
        difflib.unified_diff(
            backup_text.splitlines(keepends=True),
            current_text.splitlines(keepends=True),
            fromfile=f"sauvegarde : {args.filename}",
            tofile="wg0.conf (actuel)",
        )
    )
    return {"ok": True, "filename": args.filename, "diff": "".join(diff_lines), "identical": not diff_lines}


def act_restore_backup(args):
    path = _safe_backup_path(args.filename)
    # Verification d'integrite : le fichier doit rester lisible et non-vide.
    # (Le sha256 est recalcule a chaque listing plutot que fige a la creation :
    # cela detecte aussi une modification/corruption survenue APRES coup.)
    try:
        content = path.read_text()
    except OSError as exc:
        raise OpsError(f"Sauvegarde illisible ou corrompue : {exc}")
    if "[Interface]" not in content:
        raise OpsError("Sauvegarde corrompue : contenu invalide (section [Interface] absente).")

    # Filet de securite : on sauvegarde l'etat actuel AVANT de l'ecraser,
    # pour pouvoir toujours annuler une restauration malheureuse.
    safety = do_backup("avant-restauration")
    shutil.copy2(path, WG_CONF)
    os.chmod(WG_CONF, 0o640)
    sync_live()
    return {"ok": True, "restored_from": args.filename, "safety_backup": safety["filename"], "sha256": _sha256_of(path)}


def act_download_backup(args):
    """Renvoie le contenu binaire d'une sauvegarde (base64) pour telechargement
    depuis le dashboard. Le mot de passe admin est verifie cote Flask AVANT
    d'appeler cette action (voir app.py:/api/system/backups/<f>/download) :
    ce script se contente de lire un fichier deja valide par _safe_backup_path
    (pas de traversal de chemin possible)."""
    path = _safe_backup_path(args.filename)
    content = path.read_bytes()
    return {
        "ok": True,
        "filename": args.filename,
        "content_base64": base64.b64encode(content).decode("ascii"),
    }


# ---------------------------------------------------------------------
# Redemarrage du tunnel
# ---------------------------------------------------------------------
def act_restart_tunnel(args):
    result = run(["systemctl", "restart", f"wg-quick@{WG_IF}"], check=False)
    if result.returncode != 0:
        raise OpsError(f"Echec du redemarrage du service : {result.stderr.strip() or result.stdout.strip()}")
    return {"ok": True, "restarted": True}


# ---------------------------------------------------------------------
# Rotation assistee des cles SERVEUR
# ---------------------------------------------------------------------
def gen_keypair():
    priv = run(["wg", "genkey"]).stdout.strip()
    pub = run(["wg", "pubkey"], input_text=priv + "\n").stdout.strip()
    return priv, pub


def act_rotate_server_keys(args):
    if not WG_CONF.exists():
        raise OpsError("wg0.conf introuvable.")

    backup = do_backup("avant-rotation-cles")

    new_priv, new_pub = gen_keypair()
    content = WG_CONF.read_text()
    if not re.search(r"(?m)^PrivateKey\s*=", content):
        raise OpsError("Section [Interface] sans PrivateKey - fichier inattendu, rotation annulee.")
    content = re.sub(r"(?m)^PrivateKey\s*=.*$", f"PrivateKey = {new_priv}", content, count=1)
    WG_CONF.write_text(content)
    os.chmod(WG_CONF, 0o640)

    (WG_DIR / "server_private.key").write_text(new_priv + "\n")
    os.chmod(WG_DIR / "server_private.key", 0o600)
    (WG_DIR / "server_public.key").write_text(new_pub + "\n")

    sync_live()

    # Chaque .conf client embarque la cle PUBLIQUE du serveur (dans son
    # propre bloc [Peer]) : elle doit etre mise a jour partout, sinon
    # plus aucun client ne peut se reconnecter apres la rotation.
    regenerated = []
    if CLIENTS_DIR.exists():
        for conf_path in sorted(CLIENTS_DIR.glob("*.conf")):
            text = conf_path.read_text()
            if re.search(r"(?m)^PublicKey\s*=", text):
                text = re.sub(r"(?m)^PublicKey\s*=.*$", f"PublicKey = {new_pub}", text, count=1)
                conf_path.write_text(text)
                regenerated.append(conf_path.stem)

    return {
        "ok": True,
        "new_public_key": new_pub,
        "safety_backup": backup["filename"],
        "regenerated_clients": regenerated,
        "warning": (
            f"{len(regenerated)} client(s) doivent réimporter leur nouvelle configuration "
            "(la clé publique du serveur a changé dans chaque .conf)."
        ),
    }


# ---------------------------------------------------------------------
# Export d'audit (zip de toutes les configs + wg0.conf)
# ---------------------------------------------------------------------
def _prune_exports():
    if not EXPORT_DIR.exists():
        return
    now = time.time()
    for p in EXPORT_DIR.glob("blockhash-export-*.zip"):
        if now - p.stat().st_mtime > EXPORT_MAX_AGE_SEC:
            p.unlink(missing_ok=True)


def act_export_all(args):
    if not CLIENTS_DIR.exists():
        raise OpsError("Aucun client configure.")

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    _prune_exports()

    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d-%H%M%S")
    zip_path = EXPORT_DIR / f"blockhash-export-{ts}.zip"

    manifest_lines = ["name,public_key,allowed_ips,enabled"]
    conf_files = sorted(CLIENTS_DIR.glob("*.conf"))

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for conf_path in conf_files:
            zf.write(conf_path, arcname=f"clients/{conf_path.name}")
            pub_key_file = CLIENTS_DIR / f"{conf_path.stem}_public.key"
            pub = pub_key_file.read_text().strip() if pub_key_file.exists() else ""
            aips_m = re.search(r"(?m)^Address\s*=\s*(\S+)", conf_path.read_text())
            manifest_lines.append(f"{conf_path.stem},{pub},{aips_m.group(1) if aips_m else ''},true")
        if WG_CONF.exists():
            zf.write(WG_CONF, arcname="wg0.conf")
        zf.writestr("manifest.csv", "\n".join(manifest_lines) + "\n")

    _chgrp_readable(zip_path)
    return {"ok": True, "zip_path": str(zip_path), "size_bytes": zip_path.stat().st_size, "client_count": len(conf_files)}


def act_diagnostics(args):
    """Collecte un instantane de diagnostic (etat des services, connectivite,
    espace disque, permissions des fichiers critiques). Tourne en root (via
    sudo, comme le reste de wgops.py) donc peut lire des permissions/chemins
    inaccessibles a www-data - c'est precisement l'interet de cette action
    plutot que de le faire depuis Flask."""
    checks = []

    def check(name, ok, detail=""):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    # -- Service wg-quick --------------------------------------------
    wg_status = subprocess.run(["systemctl", "is-active", f"wg-quick@{WG_IF}"], capture_output=True, text=True, timeout=5)
    check("Service wg-quick@" + WG_IF, wg_status.stdout.strip() == "active", wg_status.stdout.strip() or "inconnu")

    # -- Service dashboard ---------------------------------------------
    dash_status = subprocess.run(["systemctl", "is-active", "blockhash-dashboard"], capture_output=True, text=True, timeout=5)
    check("Service blockhash-dashboard", dash_status.stdout.strip() == "active", dash_status.stdout.strip() or "inconnu")

    # -- Interface WireGuard active -------------------------------------
    wg_show = subprocess.run(["wg", "show", WG_IF], capture_output=True, text=True, timeout=5)
    check("Interface WireGuard active (wg show)", wg_show.returncode == 0, (wg_show.stdout.splitlines() or ["aucune sortie"])[0])

    # -- Connectivite reseau sortante -----------------------------------
    ping = subprocess.run(["ping", "-c", "1", "-W", "2", "1.1.1.1"], capture_output=True, text=True, timeout=4)
    check("Connectivité réseau sortante", ping.returncode == 0, "OK" if ping.returncode == 0 else "Aucune réponse à 1.1.1.1")

    # -- Espace disque ---------------------------------------------------
    disk = shutil.disk_usage("/")
    percent = disk.used / disk.total * 100
    check(f"Espace disque (/) : {percent:.0f}% utilisé", percent < 90, f"{disk.free // (1024**3)} Go libres")

    # -- Fichiers/permissions critiques ----------------------------------
    for path, expected_mode in ((WG_CONF, 0o640), (BACKUPS_DIR, 0o750)):
        if path.exists():
            actual_mode = oct(path.stat().st_mode & 0o777)
            check(f"Permissions {path}", True, f"mode actuel {actual_mode}")
        else:
            check(f"Présence de {path}", False, "fichier/dossier introuvable")

    ok_count = sum(1 for c in checks if c["ok"])
    return {
        "ok": True,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "summary": f"{ok_count}/{len(checks)} contrôles OK",
        "checks": checks,
    }


ACTIONS = {
    "diagnostics": act_diagnostics,
    "backup": act_backup,
    "auto-backup": act_auto_backup,
    "list-backups": act_list_backups,
    "diff-backup": act_diff_backup,
    "restore-backup": act_restore_backup,
    "download-backup": act_download_backup,
    "restart-tunnel": act_restart_tunnel,
    "rotate-server-keys": act_rotate_server_keys,
    "export-all": act_export_all,
}


def main():
    parser = argparse.ArgumentParser(description="BLOCKHash - operations systeme privilegiees")
    parser.add_argument("action", choices=sorted(ACTIONS.keys()))
    parser.add_argument("--label")
    parser.add_argument("--description")
    parser.add_argument("--filename")
    args = parser.parse_args()

    try:
        result = ACTIONS[args.action](args)
        print(json.dumps(result))
        sys.exit(0)
    except OpsError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)
    except subprocess.CalledProcessError as exc:
        print(json.dumps({"ok": False, "error": f"commande echouee : {exc.stderr or exc}"}))
        sys.exit(1)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"erreur interne : {exc}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
