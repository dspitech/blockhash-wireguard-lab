#!/usr/bin/env python3
"""
BLOCKHash - provisioning.py
=========================================================
Logique du module "Provisioning VPN depuis un annuaire" (Phase 1) :
resolution de la selection d'utilisateurs, apercu ("dry-run"), et
execution d'un job de provisioning. Reutilise entierement `run_wgctl`
(donc wgctl.py, sudo -n, generation de cles) plutot que de reimplementer
la creation de client - voir README, section 18 "Ce qu'il ne faut pas
faire" du cahier des charges d'origine.

Ne fait PAS (Phase 1, voir feuille de route dans le README) :
  - politiques par groupe (E1), rollback (E3), notifications (E4),
    quotas (E7), tags dynamiques calcules (E8), synchronisation
    periodique, detection d'orphelins (E9), reconciliation (E10).
"""

import re
import time

CLIENT_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_SLUG_RE = re.compile(r"[^A-Za-z0-9_-]+")


def check_quota(source_row: dict, additional: int) -> None:
    """E7 - leve ValueError si l'execution depasserait le plafond de
    clients configure pour cette source (quota_max, illimite si None)."""
    quota_max = source_row.get("quota_max")
    if quota_max is None:
        return
    used = source_row.get("quota_used") or 0
    if used + additional > quota_max:
        raise ValueError(
            f"Quota de la source depasse : {used} deja provisionnes, {additional} demandes, "
            f"plafond {quota_max}. Augmentez le quota ou reduisez la selection."
        )


def compute_dynamic_tags(user, templates: list) -> list:
    """E8 - calcule des tags a partir des attributs de l'utilisateur, ex.
    'ad-dept-{department}' -> 'ad-dept-commercial'. Un template dont
    l'attribut est vide/absent est simplement ignore (pas de tag
    'ad-dept-none')."""
    tags = []
    for tmpl in templates or []:
        try:
            value = tmpl.format(
                login=user.id or "", department=user.department or "", title=user.title or "",
                location=user.location or "", date=time.strftime("%Y-%m-%d"),
            )
        except (KeyError, IndexError):
            continue
        # Si un placeholder attendu etait vide, on obtient un tag mal forme
        # (ex: "ad-dept-") : on l'ignore plutot que de creer un tag inutile.
        if value.endswith("-") or "--" in value or not value.strip("-"):
            continue
        tags.append(_SLUG_RE.sub("-", value).strip("-")[:32])
    return tags


def build_client_name(template: str, user) -> str:
    """Applique un template simple ({login}, {display_name}) puis nettoie
    le resultat pour respecter les contraintes de nom de client BLOCKHash
    (CLIENT_NAME_RE, meme regle que la creation manuelle/CSV)."""
    name = (template or "{login}").format(
        login=user.id or "",
        display_name=user.display_name or "",
        department=user.department or "",
    )
    name = _SLUG_RE.sub("-", name).strip("-")
    return name[:32] or (user.id or "user")[:32]


def resolve_selection(connector, mode: str, selection: dict) -> list:
    """-> list[DirectoryUser], selon le mode de selection (F6 du cahier
    des charges : individuelle/multiple, groupe, OU, filtre)."""
    if mode == "manual":
        ids = selection.get("user_ids") or []
        return [connector.get_user(uid) for uid in ids]
    if mode == "group":
        group = selection.get("group")
        if not group:
            raise ValueError("Selection par groupe : 'group' manquant.")
        return connector.get_group_members(group)
    if mode == "ou":
        ou = selection.get("ou")
        if not ou:
            raise ValueError("Selection par OU : 'ou' manquant.")
        return connector.get_ou_members(ou)
    if mode == "filter":
        search = selection.get("search") or ""
        result = connector.list_users(search=search, page=1, page_size=selection.get("max_results", 5000))
        return result.items
    raise ValueError(f"Mode de selection invalide : {mode}")


def preview(users: list, existing_client_names: set, already_mapped: dict, options: dict) -> dict:
    """Dry-run (F7, obligatoire avant execution) : pour chaque utilisateur,
    determine s'il sera cree, ignore (deja provisionne/desactive/conflit)
    ou en erreur - sans jamais appeler wgctl.py."""
    template = options.get("template", "{login}")
    include_disabled = bool(options.get("include_disabled", False))

    rows = []
    seen_names = set()
    stats = {"will_create": 0, "already_exists": 0, "disabled_skipped": 0, "conflict": 0, "invalid": 0}

    for user in users:
        entry = {"user_id": user.id, "display_name": user.display_name, "email": user.email}

        if user.id in already_mapped:
            entry.update(status="already_exists", reason=f"Deja provisionne -> client « {already_mapped[user.id]} ».")
            stats["already_exists"] += 1
            rows.append(entry)
            continue

        if user.account_disabled and not include_disabled:
            entry.update(status="disabled_skipped", reason="Compte annuaire desactive (exclu par defaut).")
            stats["disabled_skipped"] += 1
            rows.append(entry)
            continue

        client_name = build_client_name(template, user)
        entry["planned_client_name"] = client_name

        if not CLIENT_NAME_RE.match(client_name):
            entry.update(status="invalid", reason="Nom de client genere invalide apres nettoyage du template.")
            stats["invalid"] += 1
            rows.append(entry)
            continue

        if client_name in existing_client_names or client_name in seen_names:
            entry.update(status="conflict", reason=f"Le nom de client « {client_name} » existe deja ou est en doublon dans cette selection.")
            stats["conflict"] += 1
            rows.append(entry)
            continue

        seen_names.add(client_name)
        entry.update(status="will_create", reason=None)
        stats["will_create"] += 1
        rows.append(entry)

    return {"rows": rows, "stats": stats, "total": len(rows)}


def run_job(job_id, users, existing_client_names, already_mapped, options, actor, source_id, source_mode,
            run_wgctl_fn, store_module, log_fn=None, notify_fn=None):
    """Execute effectivement le provisioning pour `users` (deja resolus).
    Concu pour tourner dans un thread separe (voir app.py, route
    /api/provision/execute) : ne renvoie rien, met a jour l'etat du job
    dans directory_store au fur et a mesure pour permettre le suivi de
    progression par polling (GET /api/provision/jobs/<id>).
    `notify_fn(job_id, stats)`, si fourni, est appele a la fin du job
    (E4 - notifications post-provisioning, voir app.py pour le branchement
    sur alerts.dispatch)."""
    plan = preview(users, existing_client_names, already_mapped, options)
    to_create = {r["user_id"]: r for r in plan["rows"] if r["status"] == "will_create"}
    users_by_id = {u.id: u for u in users}

    store_module.update_job(job_id, status="running")
    succeeded = failed = skipped = 0

    for row in plan["rows"]:
        user = users_by_id[row["user_id"]]
        if row["status"] != "will_create":
            store_module.append_log(job_id, source_id, user.id, row.get("planned_client_name") or "-",
                                      "skipped", row["reason"], actor, source_mode)
            skipped += 1
            store_module.update_job(job_id, processed=succeeded + failed + skipped, skipped=skipped)
            continue

        client_name = row["planned_client_name"]
        static_tags = [t.strip() for t in (options.get("extra_tag") or "").split(",") if t.strip()]
        dynamic_tags = compute_dynamic_tags(user, options.get("dynamic_tags"))
        all_tags = ",".join(static_tags + dynamic_tags) or None
        contact = {
            "prenom": user.display_name,
            "email": user.email,
            "telephone": user.phone,
            "fonction": user.title,
            "tags": all_tags,
        }
        try:
            run_wgctl_fn("add", name=client_name, expires_days=options.get("expires_days"), **contact)
            store_module.record_provisioning(source_id, user.id, client_name, actor, source_mode, job_id)
            store_module.append_log(job_id, source_id, user.id, client_name, "created", None, actor, source_mode)
            store_module.increment_quota_used(source_id, 1)
            succeeded += 1
        except Exception as exc:  # noqa: BLE001 - on veut journaliser toute erreur wgctl et continuer le lot
            store_module.append_log(job_id, source_id, user.id, client_name, "failed", str(exc)[:300], actor, source_mode)
            failed += 1
        store_module.update_job(job_id, processed=succeeded + failed + skipped, succeeded=succeeded, failed=failed)

    store_module.update_job(job_id, status="done", finished_at=int(time.time()))
    if notify_fn:
        try:
            notify_fn(job_id, {"succeeded": succeeded, "failed": failed, "skipped": skipped, "total": len(plan["rows"])})
        except Exception:  # noqa: BLE001 - une notification qui echoue ne doit jamais invalider le job
            pass


def run_sync(source_id, connector, mapped_users, current_directory_users, options, actor,
             run_wgctl_fn, store_module):
    """F12/F13/E9/E11 - synchronisation periodique d'une source :
      - nouveaux entrants (utilisateurs de l'annuaire non encore mappes) ->
        crees automatiquement si auto_create=True, dans la limite de
        max_auto_provisions_per_run (F12) ;
      - comptes desactives cote annuaire ET deja provisionnes -> le client
        VPN correspondant est DESACTIVE (jamais revoque automatiquement,
        voir cahier des charges "ce qu'il ne faut pas faire") via
        `run_wgctl_fn("disable", name=...)` (F13) ;
      - utilisateurs provisionnes mais disparus de l'annuaire -> marques
        orphelins (E9), jamais desactives/revoques automatiquement.
    Retourne un diff structure, persiste dans directory_sync_history (E11)."""
    directory_ids = {u.id for u in current_directory_users}
    by_id = {u.id: u for u in current_directory_users}
    max_auto = options.get("max_auto_provisions_per_run", 100)
    auto_create = options.get("auto_create", True)

    added, disabled_list, orphaned_list, errors = [], [], [], []

    # 1) Nouveaux entrants
    if auto_create:
        new_users = [u for u in current_directory_users if u.id not in mapped_users and not u.account_disabled]
        for user in new_users[:max_auto]:
            client_name = build_client_name(options.get("template", "{login}"), user)
            if not CLIENT_NAME_RE.match(client_name):
                continue
            try:
                run_wgctl_fn("add", name=client_name, expires_days=options.get("expires_days"),
                              prenom=user.display_name, email=user.email, telephone=user.phone, fonction=user.title)
                store_module.record_provisioning(source_id, user.id, client_name, actor, "sync")
                store_module.increment_quota_used(source_id, 1)
                added.append({"user_id": user.id, "client_name": client_name})
            except Exception as exc:  # noqa: BLE001
                errors.append({"user_id": user.id, "error": str(exc)[:300]})

    # 2) Comptes desactives cote annuaire, deja provisionnes -> desactivation du client (jamais revocation)
    for user_id, client_name in mapped_users.items():
        user = by_id.get(user_id)
        if user and user.account_disabled:
            try:
                run_wgctl_fn("disable", name=client_name)
                disabled_list.append({"user_id": user_id, "client_name": client_name})
            except Exception as exc:  # noqa: BLE001
                errors.append({"user_id": user_id, "error": str(exc)[:300]})
        elif user_id not in directory_ids:
            # 3) Disparu de l'annuaire -> orphelin (E9), jamais touche automatiquement
            store_module.mark_orphaned(source_id, user_id, True)
            orphaned_list.append({"user_id": user_id, "client_name": client_name})

    return {
        "added": added, "disabled": disabled_list, "orphaned": orphaned_list, "errors": errors,
    }


def rollback_job(job_id, source_id, actor, run_wgctl_fn, store_module):
    """E3 - revoque tous les clients crees par ce job (action 'created'
    dans provisioning_log). Ne touche jamais aux clients preexistants ni
    a ceux crees par un autre job."""
    logs = store_module.list_log_for_job(job_id)
    created = [entry["client_name"] for entry in logs if entry["action"] == "created"]
    revoked, failed = [], []
    for client_name in created:
        try:
            run_wgctl_fn("revoke", name=client_name)
            store_module.append_log(job_id, source_id, "-", client_name, "rolled_back", "Revoque par rollback", actor, "rollback")
            store_module.dissociate_by_client_name(client_name)
            revoked.append(client_name)
        except Exception as exc:  # noqa: BLE001 - on veut tenter la revocation de tous les clients du job
            failed.append({"client_name": client_name, "error": str(exc)[:300]})
    return {"revoked": revoked, "failed": failed}
