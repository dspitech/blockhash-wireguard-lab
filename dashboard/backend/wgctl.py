#!/usr/bin/env python3
"""
BLOCKHash - wgctl.py
=========================================================
Module privilegie de gestion du cycle de vie des clients WireGuard.

Ce script est le SEUL point d'entree qui a le droit d'ecrire dans
wg0.conf, d'appeler `wg set` / `wg syncconf` et de manipuler `tc`
(limitation de bande passante). Il est concu pour etre invoque :

  1) directement par un administrateur en SSH (via le wrapper
     scripts/06-manage-client.sh) ;
  2) par le service dashboard (gunicorn, utilisateur www-data) via
     une regle sudoers restreinte a CE fichier precis (voir
     /etc/sudoers.d/blockhash-dashboard, genere par
     scripts/03-install-dashboard.sh).

Le dashboard lui-meme (app.py, sous www-data) NE modifie jamais
wg0.conf directement : il se contente de faire
`sudo -n python3 wgctl.py <action> ...` et de relayer le JSON
renvoye sur stdout. Toute la logique sensible (validation des noms,
regeneration de cles, edition du fichier de conf, rechargement a
chaud) est centralisee ici, dans un fichier root:root non
inscriptible par www-data, ce qui limite la surface d'attaque meme
si le compte de service est compromis.

Toutes les sous-commandes ecrivent un OBJET JSON UNIQUE sur stdout
(succes -> {"ok": true, ...} / erreur -> {"ok": false, "error": "..."},
code de sortie != 0). Rien d'autre n'est ecrit sur stdout, pour que
l'appelant puisse toujours faire json.loads(stdout).

Format de bloc [Peer] dans wg0.conf (genere/relu par ce script) :

    [Peer]
    # Client : nom-client
    # Meta : {"created": "...", "expires": null, "bw_up_mbit": null, "bw_down_mbit": null}
    PublicKey = ...
    PresharedKey = ...
    AllowedIPs = 10.66.66.5/32

Un client DESACTIVE (sans etre supprime) a CHAQUE ligne de son bloc
prefixee d'un "#" supplementaire :

    #[Peer]
    ## Client : nom-client
    ## Meta : {...}
    #PublicKey = ...
    #PresharedKey = ...
    #AllowedIPs = 10.66.66.5/32

`wg-quick strip` (utilise par `wg syncconf`) retire toute ligne de
commentaire : un bloc entierement commente disparait donc de l'etat
"live" sans jamais quitter le fichier wg0.conf, ce qui permet de le
reactiver a l'identique (meme IP, memes cles) plus tard.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

WG_IF = os.environ.get("WG_INTERFACE", "wg0")
WG_DIR = Path(os.environ.get("WG_DIR", "/etc/wireguard"))
WG_CONF = Path(os.environ.get("WG_CONF_PATH", str(WG_DIR / f"{WG_IF}.conf")))
# Groupe autorise a LIRE wg0.conf (le dashboard, sous www-data, le lit
# directement en group-read - voir wgstate.py:load_peer_config). Ce script
# tourne en root (execution directe ou via sudo) : sans un chown explicite,
# le fichier recree par save_conf() appartiendrait au groupe "root" et
# deviendrait illisible par www-data des la premiere modification (ajout,
# activation/desactivation, renommage, expiration...), meme si l'installation
# initiale (03-install-dashboard.sh) avait mis les bons droits au depart.
WG_CONF_GROUP = os.environ.get("WG_CONF_GROUP", "www-data")
CLIENTS_DIR = WG_DIR / "clients"
REVOKED_DIR = CLIENTS_DIR / "revoked"
ENDPOINT_CACHE = WG_DIR / "server_endpoint.txt"
WG_PORT = os.environ.get("WG_PORT", "51820")
WG_SUBNET = os.environ.get("WG_SERVER_SUBNET", "10.66.66")
CLIENT_DNS = os.environ.get("WG_CLIENT_DNS", "1.1.1.1")

NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
PEER_START_RE = re.compile(r"^#{0,2}\[Peer\]\s*$")


class CtlError(Exception):
    """Erreur controlee -> renvoyee proprement en JSON, jamais de trace."""


# ---------------------------------------------------------------------
# Utilitaires bas niveau
# ---------------------------------------------------------------------
def run(cmd, input_text=None, check=True):
    return subprocess.run(
        cmd, input=input_text, text=True, capture_output=True, check=check
    )


def run_bash(script, check=True):
    """Pour les constructions necessitant bash (process substitution)."""
    return subprocess.run(
        ["bash", "-c", script], text=True, capture_output=True, check=check
    )


def require_name(name):
    if not name or not NAME_RE.match(name):
        raise CtlError(
            "Nom de client invalide : lettres/chiffres/tirets/underscores, 32 caracteres max."
        )
    return name


def now_iso():
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------
# Parsing / rendu de wg0.conf
# ---------------------------------------------------------------------
class Peer:
    def __init__(self, name, public_key, preshared_key, allowed_ips, enabled, meta):
        self.name = name
        self.public_key = public_key
        self.preshared_key = preshared_key
        self.allowed_ips = allowed_ips
        self.enabled = enabled
        self.meta = meta or {}

    def to_dict(self):
        d = {
            "name": self.name,
            "public_key": self.public_key,
            "allowed_ips": self.allowed_ips,
            "enabled": self.enabled,
        }
        d.update(self.meta)
        return d

    def render(self):
        meta_json = json.dumps(self.meta, separators=(",", ":"), sort_keys=True)
        lines = [
            "[Peer]",
            f"# Client : {self.name}",
            f"# Meta : {meta_json}",
            f"PublicKey = {self.public_key}",
        ]
        if self.preshared_key:
            lines.append(f"PresharedKey = {self.preshared_key}")
        lines.append(f"AllowedIPs = {self.allowed_ips}")
        block = "\n".join(lines)
        if not self.enabled:
            block = "\n".join("#" + line for line in block.splitlines())
        return block


def load_conf():
    if not WG_CONF.exists():
        raise CtlError(f"Fichier introuvable : {WG_CONF}")
    content = WG_CONF.read_text()

    lines = content.splitlines()
    starts = [i for i, ln in enumerate(lines) if PEER_START_RE.match(ln)]
    header = "\n".join(lines[: starts[0]]).rstrip("\n") if starts else content.rstrip("\n")

    peers = []
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
        raw_block = lines[start:end]
        # Retire les lignes vides de fin de bloc
        while raw_block and raw_block[-1].strip() == "":
            raw_block.pop()

        disabled = raw_block[0].startswith("#")
        # Decommente une fois toutes les lignes si le bloc est desactive
        canon = [ln[1:] if (disabled and ln.startswith("#")) else ln for ln in raw_block]
        canon_text = "\n".join(canon)

        name_m = re.search(r"^#\s*Client\s*:\s*(.+)$", canon_text, re.MULTILINE)
        meta_m = re.search(r"^#\s*Meta\s*:\s*(\{.*\})\s*$", canon_text, re.MULTILINE)
        pub_m = re.search(r"^PublicKey\s*=\s*(\S+)", canon_text, re.MULTILINE)
        psk_m = re.search(r"^PresharedKey\s*=\s*(\S+)", canon_text, re.MULTILINE)
        aips_m = re.search(r"^AllowedIPs\s*=\s*(\S+)", canon_text, re.MULTILINE)

        if not pub_m:
            continue  # bloc [Peer] non reconnu (ajoute manuellement) -> ignore

        name = name_m.group(1).strip() if name_m else pub_m.group(1)[:8] + "…"
        try:
            meta = json.loads(meta_m.group(1)) if meta_m else {}
        except json.JSONDecodeError:
            meta = {}

        peers.append(
            Peer(
                name=name,
                public_key=pub_m.group(1),
                preshared_key=psk_m.group(1) if psk_m else None,
                allowed_ips=aips_m.group(1) if aips_m else "",
                enabled=not disabled,
                meta=meta,
            )
        )
    return header, peers


def save_conf(header, peers):
    parts = [header.rstrip("\n")]
    for p in peers:
        parts.append("")
        parts.append(p.render())
    text = "\n".join(parts) + "\n"

    tmp = WG_CONF.with_suffix(".conf.tmp")
    tmp.write_text(text)
    os.chmod(tmp, 0o640)
    _chown_group_best_effort(tmp, WG_CONF_GROUP)
    tmp.replace(WG_CONF)


def _chown_group_best_effort(path, group_name):
    """Ajuste uniquement le groupe (conserve owner root) pour que www-data
    puisse lire le fichier sans droits supplementaires. Ne doit jamais faire
    echouer l'operation appelante (ex: tests lances par un utilisateur sans
    ce groupe, ou plateforme sans module `grp`)."""
    try:
        import grp

        gid = grp.getgrnam(group_name).gr_gid
        os.chown(path, 0, gid)
    except (KeyError, PermissionError, OSError, ImportError):
        pass


def sync_live():
    """Recharge wg0 a chaud (sans coupure des tunnels deja actifs)."""
    result = run_bash(f"wg syncconf {WG_IF} <(wg-quick strip {WG_IF})", check=False)
    if result.returncode != 0:
        raise CtlError(f"wg syncconf a echoue : {result.stderr.strip()}")


def find_peer(peers, name, required=True):
    for p in peers:
        if p.name.lower() == name.lower():
            return p
    if required:
        raise CtlError(f"Client inconnu : {name}")
    return None


def next_free_ip(peers):
    used = set()
    for p in peers:
        m = re.match(rf"{re.escape(WG_SUBNET)}\.(\d+)", p.allowed_ips)
        if m:
            used.add(int(m.group(1)))
    octet = 2
    while octet in used:
        octet += 1
    if octet > 254:
        raise CtlError("Plus d'adresse IP libre dans le sous-reseau du tunnel.")
    return f"{WG_SUBNET}.{octet}/32"


# ---------------------------------------------------------------------
# Cles / config client / QR
# ---------------------------------------------------------------------
def gen_keypair():
    priv = run(["wg", "genkey"]).stdout.strip()
    pub = run(["wg", "pubkey"], input_text=priv + "\n").stdout.strip()
    psk = run(["wg", "genpsk"]).stdout.strip()
    return priv, pub, psk


def server_public_key():
    path = WG_DIR / "server_public.key"
    if not path.exists():
        raise CtlError("Cle publique serveur introuvable (server_public.key).")
    return path.read_text().strip()


def server_endpoint():
    if ENDPOINT_CACHE.exists():
        cached = ENDPOINT_CACHE.read_text().strip()
        if cached:
            return cached
    result = run(["curl", "-s", "ifconfig.me"], check=False)
    ip = result.stdout.strip()
    if not ip:
        result = run(["curl", "-s", "ipinfo.io/ip"], check=False)
        ip = result.stdout.strip()
    if not ip:
        raise CtlError("Impossible de determiner l'IP publique du serveur.")
    ENDPOINT_CACHE.write_text(ip + "\n")
    return ip


def write_client_files(name, private_key, public_key, psk, allowed_ips):
    CLIENTS_DIR.mkdir(parents=True, exist_ok=True)
    os.umask(0o077)

    (CLIENTS_DIR / f"{name}_private.key").write_text(private_key + "\n")
    (CLIENTS_DIR / f"{name}_public.key").write_text(public_key + "\n")
    (CLIENTS_DIR / f"{name}_preshared.key").write_text(psk + "\n")

    conf_text = (
        "[Interface]\n"
        f"PrivateKey = {private_key}\n"
        f"Address = {allowed_ips}\n"
        f"DNS = {CLIENT_DNS}\n"
        "\n"
        "[Peer]\n"
        f"PublicKey = {server_public_key()}\n"
        f"PresharedKey = {psk}\n"
        f"Endpoint = {server_endpoint()}:{WG_PORT}\n"
        "AllowedIPs = 0.0.0.0/0\n"
        "PersistentKeepalive = 25\n"
    )
    conf_path = CLIENTS_DIR / f"{name}.conf"
    conf_path.write_text(conf_text)
    os.chmod(conf_path, 0o600)
    return conf_path, conf_text


def qr_png_base64(conf_text):
    import base64

    result = run(["qrencode", "-t", "PNG", "-o", "-"], input_text=None, check=False)
    # qrencode ne lit pas bien un input texte via subprocess.run(text=True) pour du binaire
    # en sortie -> on repasse par des octets explicitement.
    proc = subprocess.run(
        ["qrencode", "-t", "PNG", "-o", "-"],
        input=conf_text.encode(),
        capture_output=True,
        check=True,
    )
    return base64.b64encode(proc.stdout).decode()


# ---------------------------------------------------------------------
# Limitation de bande passante (tc / HTB) — best effort, avance
# ---------------------------------------------------------------------
def _octet_of(allowed_ips):
    m = re.match(rf"{re.escape(WG_SUBNET)}\.(\d+)", allowed_ips)
    if not m:
        raise CtlError("AllowedIPs inattendu pour la limitation de debit.")
    return int(m.group(1))


def apply_bandwidth(peer, up_mbit, down_mbit):
    """
    Limite le debit d'un pair via tc/HTB directement sur l'interface wg0 :
      - "down" (vers le client) = trafic EMIS par le serveur -> classe HTB
        en sortie sur wg0, filtree par IP DEST = AllowedIPs du pair.
      - "up" (depuis le client) = trafic RECU par le serveur -> pas de
        controle de sortie possible sans IFB ; on utilise donc un ingress
        qdisc + une redirection vers une interface ifb dediee (ifb-wg0).
    Best effort : necessite le module noyau `ifb` et `iproute2`. Si tc
    echoue, l'action est annulee (la limite n'est pas appliquee) mais
    n'empeche pas le reste de l'operation (le peer reste actif).
    """
    classid = 0x10 + _octet_of(peer.allowed_ips)  # id de classe unique par IP
    dest_ip = peer.allowed_ips.split("/")[0]

    def q(cmd, check=False):
        return run(cmd, check=check)

    down_ok = True
    up_ok = True

    # Racine HTB de sortie (debit descendant, vers le client) sur wg0
    q(["tc", "qdisc", "add", "dev", WG_IF, "root", "handle", "1:", "htb", "default", "999"])
    q(["tc", "class", "del", "dev", WG_IF, "classid", f"1:{classid}"])
    q(["tc", "filter", "del", "dev", WG_IF, "protocol", "ip", "parent", "1:", "prio", "1",
       "u32", "match", "ip", "dst", dest_ip])

    if down_mbit:
        r1 = q(["tc", "class", "add", "dev", WG_IF, "parent", "1:", "classid", f"1:{classid}",
                "htb", "rate", f"{down_mbit}mbit", "ceil", f"{down_mbit}mbit"])
        r2 = q(["tc", "filter", "add", "dev", WG_IF, "protocol", "ip", "parent", "1:", "prio", "1",
                "u32", "match", "ip", "dst", dest_ip, "flowid", f"1:{classid}"])
        down_ok = r1.returncode == 0 and r2.returncode == 0

    # Debit montant (upload client) : redirection ingress -> ifb-wg0
    ifb = f"ifb-{WG_IF}"
    q(["ip", "link", "add", ifb, "type", "ifb"])
    q(["ip", "link", "set", ifb, "up"])
    q(["tc", "qdisc", "add", "dev", WG_IF, "ingress"])
    q(["tc", "filter", "add", "dev", WG_IF, "parent", "ffff:", "protocol", "ip",
       "u32", "match", "u32", "0", "0", "action", "mirred", "egress", "redirect", "dev", ifb])
    q(["tc", "qdisc", "add", "dev", ifb, "root", "handle", "1:", "htb", "default", "999"])
    q(["tc", "class", "del", "dev", ifb, "classid", f"1:{classid}"])
    q(["tc", "filter", "del", "dev", ifb, "protocol", "ip", "parent", "1:", "prio", "1",
       "u32", "match", "ip", "src", dest_ip])

    if up_mbit:
        r3 = q(["tc", "class", "add", "dev", ifb, "parent", "1:", "classid", f"1:{classid}",
                "htb", "rate", f"{up_mbit}mbit", "ceil", f"{up_mbit}mbit"])
        r4 = q(["tc", "filter", "add", "dev", ifb, "protocol", "ip", "parent", "1:", "prio", "1",
                "u32", "match", "ip", "src", dest_ip, "flowid", f"1:{classid}"])
        up_ok = r3.returncode == 0 and r4.returncode == 0

    if not down_mbit and not up_mbit:
        return True  # limite retiree -> rien a verifier
    return down_ok and up_ok


# ---------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------
def act_list(args):
    _, peers = load_conf()
    return {"ok": True, "peers": [p.to_dict() for p in peers]}


def act_add(args):
    name = require_name(args.name)
    header, peers = load_conf()
    if find_peer(peers, name, required=False):
        raise CtlError(f"Un client nomme '{name}' existe deja.")

    allowed_ips = next_free_ip(peers)
    priv, pub, psk = gen_keypair()

    meta = {"created": now_iso(), "expires": None, "bw_up_mbit": None, "bw_down_mbit": None}
    if args.expires_days:
        meta["expires"] = (
            datetime.now(tz=timezone.utc) + timedelta(days=int(args.expires_days))
        ).date().isoformat()

    peer = Peer(name, pub, psk, allowed_ips, enabled=True, meta=meta)
    peers.append(peer)
    save_conf(header, peers)
    sync_live()

    conf_path, conf_text = write_client_files(name, priv, pub, psk, allowed_ips)
    return {
        "ok": True,
        "name": name,
        "allowed_ips": allowed_ips,
        "public_key": pub,
        "expires": meta["expires"],
        "conf_path": str(conf_path),
        "conf_text": conf_text,
        "qr_base64": qr_png_base64(conf_text),
    }


def act_enable(args):
    name = require_name(args.name)
    header, peers = load_conf()
    peer = find_peer(peers, name)
    peer.enabled = True
    save_conf(header, peers)
    sync_live()
    return {"ok": True, "name": name, "enabled": True}


def act_disable(args):
    name = require_name(args.name)
    header, peers = load_conf()
    peer = find_peer(peers, name)
    peer.enabled = False
    save_conf(header, peers)
    sync_live()
    return {"ok": True, "name": name, "enabled": False}


def act_rename(args):
    old = require_name(args.name)
    new = require_name(args.new_name)
    header, peers = load_conf()
    peer = find_peer(peers, old)
    if find_peer(peers, new, required=False):
        raise CtlError(f"Un client nomme '{new}' existe deja.")
    peer.name = new
    save_conf(header, peers)
    # Le peer est deja "live" (cles inchangees) -> pas besoin de re-syncconf,
    # mais on le fait quand meme pour rester source-of-truth-consistent.
    sync_live()

    for suffix in ("_private.key", "_public.key", "_preshared.key", ".conf"):
        src = CLIENTS_DIR / f"{old}{suffix}"
        if src.exists():
            src.rename(CLIENTS_DIR / f"{new}{suffix}")
    return {"ok": True, "old_name": old, "new_name": new}


def act_revoke(args):
    name = require_name(args.name)
    header, peers = load_conf()
    peer = find_peer(peers, name)
    peers = [p for p in peers if p is not peer]
    save_conf(header, peers)
    sync_live()

    REVOKED_DIR.mkdir(parents=True, exist_ok=True)
    for suffix in ("_private.key", "_public.key", "_preshared.key", ".conf"):
        src = CLIENTS_DIR / f"{name}{suffix}"
        if src.exists():
            src.rename(REVOKED_DIR / f"{src.name}.{datetime.now().strftime('%Y%m%d%H%M%S')}")
    return {"ok": True, "name": name, "revoked": True}


def act_regenerate(args):
    name = require_name(args.name)
    header, peers = load_conf()
    peer = find_peer(peers, name)

    priv, pub, psk = gen_keypair()
    old_pub = peer.public_key
    peer.public_key = pub
    peer.preshared_key = psk
    save_conf(header, peers)
    sync_live()
    # Retire explicitement l'ancienne cle publique du live-set si elle trainait
    # encore (peer desactive puis regenere, par exemple).
    run(["wg", "set", WG_IF, "peer", old_pub, "remove"], check=False)

    conf_path, conf_text = write_client_files(name, priv, pub, psk, peer.allowed_ips)
    return {
        "ok": True,
        "name": name,
        "public_key": pub,
        "conf_path": str(conf_path),
        "conf_text": conf_text,
        "qr_base64": qr_png_base64(conf_text),
    }


def act_get_config(args):
    name = require_name(args.name)
    _, peers = load_conf()
    find_peer(peers, name)  # 404 propre si le client n'existe pas/plus
    conf_path = CLIENTS_DIR / f"{name}.conf"
    if not conf_path.exists():
        raise CtlError(
            "Fichier de configuration introuvable pour ce client "
            "(utilisez l'action 'regenerate' pour en recreer un)."
        )
    conf_text = conf_path.read_text()
    return {"ok": True, "name": name, "conf_text": conf_text, "qr_base64": qr_png_base64(conf_text)}


def act_set_expiry(args):
    name = require_name(args.name)
    header, peers = load_conf()
    peer = find_peer(peers, name)
    if args.expires in (None, "", "none", "None"):
        peer.meta["expires"] = None
    else:
        try:
            datetime.strptime(args.expires, "%Y-%m-%d")
        except ValueError:
            raise CtlError("Date invalide, format attendu AAAA-MM-JJ.")
        peer.meta["expires"] = args.expires
    save_conf(header, peers)
    return {"ok": True, "name": name, "expires": peer.meta["expires"]}


def act_set_bandwidth(args):
    name = require_name(args.name)
    header, peers = load_conf()
    peer = find_peer(peers, name)

    up = None if args.bw_up in (None, "", "none") else int(args.bw_up)
    down = None if args.bw_down in (None, "", "none") else int(args.bw_down)

    peer.meta["bw_up_mbit"] = up
    peer.meta["bw_down_mbit"] = down
    save_conf(header, peers)

    tc_applied = False
    tc_error = None
    try:
        tc_applied = apply_bandwidth(peer, up, down)
    except Exception as exc:  # best effort : la limite logique est deja enregistree
        tc_error = str(exc)

    return {
        "ok": True,
        "name": name,
        "bw_up_mbit": up,
        "bw_down_mbit": down,
        "tc_applied": tc_applied,
        "tc_error": tc_error,
    }


def act_check_expirations(args):
    header, peers = load_conf()
    today = datetime.now(tz=timezone.utc).date().isoformat()
    disabled = []
    for p in peers:
        exp = p.meta.get("expires")
        if p.enabled and exp and exp <= today:
            p.enabled = False
            disabled.append(p.name)
    if disabled:
        save_conf(header, peers)
        sync_live()
    return {"ok": True, "disabled": disabled}


ACTIONS = {
    "list": act_list,
    "add": act_add,
    "enable": act_enable,
    "disable": act_disable,
    "rename": act_rename,
    "revoke": act_revoke,
    "regenerate": act_regenerate,
    "get-config": act_get_config,
    "set-expiry": act_set_expiry,
    "set-bandwidth": act_set_bandwidth,
    "check-expirations": act_check_expirations,
}


def main():
    parser = argparse.ArgumentParser(description="BLOCKHash - controle privilegie des clients WireGuard")
    parser.add_argument("action", choices=sorted(ACTIONS.keys()))
    parser.add_argument("--name")
    parser.add_argument("--new-name")
    parser.add_argument("--expires-days")
    parser.add_argument("--expires")
    parser.add_argument("--bw-up")
    parser.add_argument("--bw-down")
    args = parser.parse_args()

    try:
        result = ACTIONS[args.action](args)
        print(json.dumps(result))
        sys.exit(0)
    except CtlError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)
    except subprocess.CalledProcessError as exc:
        print(json.dumps({"ok": False, "error": f"commande echouee : {exc.stderr or exc}"}))
        sys.exit(1)
    except Exception as exc:  # filet de securite : jamais de trace Python brute sur stdout
        print(json.dumps({"ok": False, "error": f"erreur interne : {exc}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
