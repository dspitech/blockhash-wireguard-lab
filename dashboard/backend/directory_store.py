#!/usr/bin/env python3
"""
BLOCKHash - directory_store.py
=========================================================
Persistance du module "Provisioning VPN depuis un annuaire" (Phase 1).
Reutilise la meme base SQLite et le meme helper de connexion que
store.py (`store.get_conn()`), plutot que d'ouvrir un second fichier -
memes garanties (WAL, meme repertoire, meme sauvegarde). Suit la
convention deja en place dans store.py : chaque fonction publique
appelle `init_db()` en entree (CREATE TABLE IF NOT EXISTS, idempotent,
peu couteux) plutot qu'une initialisation centralisee au demarrage.

Tables couvertes en Phase 1 (voir README pour le detail des tables
prevues par le cahier des charges mais differees en Phase 2 :
`provisioning_policies`, `directory_users_cache`, `directory_sync_history`) :
  - directory_sources         : sources d'annuaire configurees
  - directory_provisioning_map: correspondance utilisateur annuaire <-> client VPN
  - provisioning_log          : une ligne par utilisateur traite dans un job
  - provisioning_jobs         : suivi des jobs de provisioning (asynchrones)

Secrets : `directory_sources.config_json` ne contient JAMAIS de mot de
passe. Le mot de passe de bind LDAP est lu depuis la variable
d'environnement dont le nom est stocke dans `secret_env_var` (voir
`resolve_secret`) - typiquement injectee via le fichier d'environnement
du service systemd, hors du controle de version (voir README section
configuration, variable AD_BIND_PASSWORD_<SOURCE_ID>).
"""

import json
import os
import sqlite3
import time
import uuid
from contextlib import closing

import store  # reutilise get_conn() / DB_PATH - voir docstring ci-dessus

VALID_SOURCE_TYPES = (
    "ldap_ad", "ldap_openldap", "ldap_samba", "ldap_freeipa",
    "ldap_jumpcloud", "ldap_google_secure", "ldap_azure_ad_ds", "ldap_generic",
    "graph", "google_workspace",
)
VALID_JOB_MODES = ("manual", "bulk", "group", "ou", "filter", "tenant")
VALID_JOB_STATUSES = ("pending", "running", "done", "failed", "cancelled")
VALID_LOG_ACTIONS = ("created", "updated", "skipped", "failed", "disabled", "rolled_back")


def init_db():
    with closing(store.get_conn()) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS directory_sources (
                id              TEXT PRIMARY KEY,
                name            TEXT NOT NULL UNIQUE,
                type            TEXT NOT NULL,
                config_json     TEXT NOT NULL,
                secret_env_var  TEXT,
                enabled         INTEGER DEFAULT 1,
                read_only       INTEGER DEFAULT 0,
                quota_max       INTEGER,
                last_test_at    INTEGER,
                last_test_ok    INTEGER,
                last_test_error TEXT,
                created_at      INTEGER NOT NULL,
                updated_at      INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS directory_provisioning_map (
                source_id       TEXT NOT NULL,
                user_id         TEXT NOT NULL,
                client_name     TEXT NOT NULL UNIQUE,
                provisioned_at  INTEGER NOT NULL,
                provisioned_by  TEXT NOT NULL,
                source_mode     TEXT NOT NULL,
                job_id          TEXT,
                PRIMARY KEY (source_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS provisioning_log (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id        TEXT,
                source_id     TEXT NOT NULL,
                user_id       TEXT NOT NULL,
                client_name   TEXT NOT NULL,
                action        TEXT NOT NULL,
                reason        TEXT,
                actor         TEXT NOT NULL,
                source_mode   TEXT NOT NULL,
                created_at    INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS provisioning_jobs (
                id              TEXT PRIMARY KEY,
                source_id       TEXT NOT NULL,
                mode            TEXT NOT NULL,
                options_json    TEXT NOT NULL,
                status          TEXT NOT NULL,
                total           INTEGER NOT NULL,
                processed       INTEGER DEFAULT 0,
                succeeded       INTEGER DEFAULT 0,
                failed          INTEGER DEFAULT 0,
                skipped         INTEGER DEFAULT 0,
                error           TEXT,
                started_by      TEXT NOT NULL,
                started_at      INTEGER NOT NULL,
                finished_at     INTEGER
            );

            CREATE INDEX IF NOT EXISTS idx_prov_map_client ON directory_provisioning_map(client_name);
            CREATE INDEX IF NOT EXISTS idx_prov_log_job ON provisioning_log(job_id);
            CREATE INDEX IF NOT EXISTS idx_prov_jobs_status ON provisioning_jobs(status);

            CREATE TABLE IF NOT EXISTS provisioning_policies (
                id                TEXT PRIMARY KEY,
                source_id         TEXT NOT NULL,
                group_id          TEXT NOT NULL,
                name              TEXT NOT NULL,
                template          TEXT DEFAULT '{login}',
                expires_days      INTEGER,
                tags_json         TEXT,
                dynamic_tags_json TEXT,
                created_at        INTEGER NOT NULL,
                UNIQUE (source_id, group_id)
            );

            CREATE TABLE IF NOT EXISTS directory_sync_history (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id    TEXT NOT NULL,
                started_at   INTEGER NOT NULL,
                finished_at  INTEGER,
                status       TEXT NOT NULL,
                added        INTEGER DEFAULT 0,
                disabled     INTEGER DEFAULT 0,
                errors       INTEGER DEFAULT 0,
                diff_json    TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_sync_history_source ON directory_sync_history(source_id);
            """
        )
        conn.commit()
        # Migration idempotente (meme pattern que store.py) : colonnes
        # ajoutees apres la premiere livraison du module, sur une base qui
        # pouvait deja exister.
        for column_def in ("quota_used INTEGER DEFAULT 0",):
            try:
                conn.execute(f"ALTER TABLE directory_sources ADD COLUMN {column_def}")
                conn.commit()
            except sqlite3.OperationalError:
                pass  # colonne deja presente
        for column_def in ("orphaned INTEGER DEFAULT 0",):
            try:
                conn.execute(f"ALTER TABLE directory_provisioning_map ADD COLUMN {column_def}")
                conn.commit()
            except sqlite3.OperationalError:
                pass


# --------------------------------------------------------------- sources
def create_source(name, type_, config, secret_env_var=None, read_only=False, quota_max=None):
    if type_ not in VALID_SOURCE_TYPES:
        raise ValueError(f"Type de source invalide : {type_}")
    init_db()
    now = int(time.time())
    src_id = str(uuid.uuid4())
    with closing(store.get_conn()) as conn:
        conn.execute(
            "INSERT INTO directory_sources (id, name, type, config_json, secret_env_var, enabled, "
            "read_only, quota_max, created_at, updated_at) VALUES (?,?,?,?,?,1,?,?,?,?)",
            (src_id, name, type_, json.dumps(config), secret_env_var, int(read_only), quota_max, now, now),
        )
        conn.commit()
    return src_id


def list_sources():
    init_db()
    with closing(store.get_conn()) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM directory_sources ORDER BY name").fetchall()
        return [dict(r) for r in rows]


def get_source(source_id):
    init_db()
    with closing(store.get_conn()) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM directory_sources WHERE id = ?", (source_id,)).fetchone()
        return dict(row) if row else None


def update_source(source_id, **fields):
    init_db()
    allowed = {"name", "config_json", "secret_env_var", "enabled", "read_only", "quota_max"}
    sets, params = [], []
    for k, v in fields.items():
        if k not in allowed:
            continue
        sets.append(f"{k} = ?")
        params.append(v)
    if not sets:
        return
    sets.append("updated_at = ?")
    params.append(int(time.time()))
    params.append(source_id)
    with closing(store.get_conn()) as conn:
        conn.execute(f"UPDATE directory_sources SET {', '.join(sets)} WHERE id = ?", params)
        conn.commit()


def delete_source(source_id):
    init_db()
    with closing(store.get_conn()) as conn:
        conn.execute("DELETE FROM directory_sources WHERE id = ?", (source_id,))
        conn.commit()


def record_test_result(source_id, ok, detail):
    init_db()
    with closing(store.get_conn()) as conn:
        conn.execute(
            "UPDATE directory_sources SET last_test_at = ?, last_test_ok = ?, last_test_error = ? WHERE id = ?",
            (int(time.time()), int(ok), None if ok else detail, source_id),
        )
        conn.commit()


def resolve_secret(source_row) -> str:
    """Lit le mot de passe de bind depuis la variable d'environnement
    referencee par la source - jamais depuis config_json (voir docstring
    du module)."""
    env_var = source_row.get("secret_env_var")
    if not env_var:
        return ""
    return os.environ.get(env_var, "")


def increment_quota_used(source_id, n=1):
    """E7 - incremente le compteur de clients crees depuis cette source.
    Ne verifie pas le plafond ici : voir provisioning.check_quota, appele
    AVANT execution pour refuser un job qui depasserait le quota."""
    init_db()
    with closing(store.get_conn()) as conn:
        conn.execute("UPDATE directory_sources SET quota_used = COALESCE(quota_used, 0) + ? WHERE id = ?", (n, source_id))
        conn.commit()


# ------------------------------------------------------- politiques (E1)
def create_policy(source_id, group_id, name, template="{login}", expires_days=None, tags=None, dynamic_tags=None):
    init_db()
    now = int(time.time())
    pid = str(uuid.uuid4())
    with closing(store.get_conn()) as conn:
        conn.execute(
            "INSERT INTO provisioning_policies (id, source_id, group_id, name, template, expires_days, "
            "tags_json, dynamic_tags_json, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (pid, source_id, group_id, name, template, expires_days, json.dumps(tags or []), json.dumps(dynamic_tags or []), now),
        )
        conn.commit()
    return pid


def list_policies(source_id=None):
    init_db()
    with closing(store.get_conn()) as conn:
        conn.row_factory = sqlite3.Row
        if source_id:
            rows = conn.execute("SELECT * FROM provisioning_policies WHERE source_id = ? ORDER BY name", (source_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM provisioning_policies ORDER BY name").fetchall()
        return [dict(r) for r in rows]


def get_policy_for_group(source_id, group_id):
    init_db()
    with closing(store.get_conn()) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM provisioning_policies WHERE source_id = ? AND group_id = ?", (source_id, group_id)
        ).fetchone()
        return dict(row) if row else None


def delete_policy(policy_id):
    init_db()
    with closing(store.get_conn()) as conn:
        conn.execute("DELETE FROM provisioning_policies WHERE id = ?", (policy_id,))
        conn.commit()


# ------------------------------------------------- orphelins & reconciliation (E9/E10)
def mark_orphaned(source_id, user_id, orphaned=True):
    init_db()
    with closing(store.get_conn()) as conn:
        conn.execute(
            "UPDATE directory_provisioning_map SET orphaned = ? WHERE source_id = ? AND user_id = ?",
            (int(orphaned), source_id, user_id),
        )
        conn.commit()


def list_orphans(source_id):
    init_db()
    with closing(store.get_conn()) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM directory_provisioning_map WHERE source_id = ? AND orphaned = 1", (source_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def reconcile(source_id, user_id, client_name, actor):
    """E10 - associe retroactivement un client VPN existant (cree
    manuellement ou par CSV) a un utilisateur d'annuaire."""
    record_provisioning(source_id, user_id, client_name, actor, "reconciled", job_id=None)


def dissociate(source_id, user_id):
    init_db()
    with closing(store.get_conn()) as conn:
        conn.execute("DELETE FROM directory_provisioning_map WHERE source_id = ? AND user_id = ?", (source_id, user_id))
        conn.commit()


def dissociate_by_client_name(client_name):
    init_db()
    with closing(store.get_conn()) as conn:
        conn.execute("DELETE FROM directory_provisioning_map WHERE client_name = ?", (client_name,))
        conn.commit()


# --------------------------------------------------------- synchronisation (E11/F12/F13)
def create_sync_history(source_id):
    init_db()
    with closing(store.get_conn()) as conn:
        cur = conn.execute(
            "INSERT INTO directory_sync_history (source_id, started_at, status) VALUES (?,?,?)",
            (source_id, int(time.time()), "running"),
        )
        conn.commit()
        return cur.lastrowid


def finish_sync_history(sync_id, status, added=0, disabled=0, errors=0, diff=None):
    init_db()
    with closing(store.get_conn()) as conn:
        conn.execute(
            "UPDATE directory_sync_history SET finished_at = ?, status = ?, added = ?, disabled = ?, errors = ?, diff_json = ? WHERE id = ?",
            (int(time.time()), status, added, disabled, errors, json.dumps(diff or {}), sync_id),
        )
        conn.commit()


def list_sync_history(source_id, limit=20):
    init_db()
    with closing(store.get_conn()) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM directory_sync_history WHERE source_id = ? ORDER BY started_at DESC LIMIT ?", (source_id, limit)
        ).fetchall()
        return [dict(r) for r in rows]


# ------------------------------------------------------------- provisioning map
def get_provisioning_map(source_id) -> dict:
    """-> {user_id: client_name} pour une source, utilise par le dry-run
    pour detecter les utilisateurs deja provisionnes."""
    init_db()
    with closing(store.get_conn()) as conn:
        rows = conn.execute(
            "SELECT user_id, client_name FROM directory_provisioning_map WHERE source_id = ?", (source_id,)
        ).fetchall()
        return {r[0]: r[1] for r in rows}


def record_provisioning(source_id, user_id, client_name, actor, source_mode, job_id=None):
    init_db()
    with closing(store.get_conn()) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO directory_provisioning_map "
            "(source_id, user_id, client_name, provisioned_at, provisioned_by, source_mode, job_id) "
            "VALUES (?,?,?,?,?,?,?)",
            (source_id, user_id, client_name, int(time.time()), actor, source_mode, job_id),
        )
        conn.commit()


# --------------------------------------------------------------- jobs & log
def create_job(source_id, mode, options, total, actor):
    if mode not in VALID_JOB_MODES:
        raise ValueError(f"Mode de job invalide : {mode}")
    init_db()
    job_id = f"prov_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    with closing(store.get_conn()) as conn:
        conn.execute(
            "INSERT INTO provisioning_jobs (id, source_id, mode, options_json, status, total, "
            "started_by, started_at) VALUES (?,?,?,?,?,?,?,?)",
            (job_id, source_id, mode, json.dumps(options), "pending", total, actor, int(time.time())),
        )
        conn.commit()
    return job_id


def update_job(job_id, **fields):
    init_db()
    allowed = {"status", "processed", "succeeded", "failed", "skipped", "error", "finished_at"}
    sets, params = [], []
    for k, v in fields.items():
        if k not in allowed:
            continue
        sets.append(f"{k} = ?")
        params.append(v)
    if not sets:
        return
    params.append(job_id)
    with closing(store.get_conn()) as conn:
        conn.execute(f"UPDATE provisioning_jobs SET {', '.join(sets)} WHERE id = ?", params)
        conn.commit()


def get_job(job_id):
    init_db()
    with closing(store.get_conn()) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM provisioning_jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def list_jobs(limit=50):
    init_db()
    with closing(store.get_conn()) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM provisioning_jobs ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def append_log(job_id, source_id, user_id, client_name, action, reason, actor, source_mode):
    if action not in VALID_LOG_ACTIONS:
        raise ValueError(f"Action de log invalide : {action}")
    init_db()
    with closing(store.get_conn()) as conn:
        conn.execute(
            "INSERT INTO provisioning_log (job_id, source_id, user_id, client_name, action, reason, "
            "actor, source_mode, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (job_id, source_id, user_id, client_name, action, reason, actor, source_mode, int(time.time())),
        )
        conn.commit()


def list_log_for_job(job_id):
    init_db()
    with closing(store.get_conn()) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM provisioning_log WHERE job_id = ? ORDER BY id", (job_id,)
        ).fetchall()
        return [dict(r) for r in rows]
