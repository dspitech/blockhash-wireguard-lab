"""Tests pour directory_store.py (persistance) et provisioning.py (dry-run, execution)."""

import pytest


def test_create_and_list_source(wg_env, fresh_modules):
    import directory_store as ds

    sid = ds.create_source("AD Test", "ldap_ad", {"host": "ad.local", "base_dn": "dc=test"}, secret_env_var="AD_BIND_PASSWORD_TEST")
    sources = ds.list_sources()
    assert len(sources) == 1
    assert sources[0]["id"] == sid
    assert sources[0]["secret_env_var"] == "AD_BIND_PASSWORD_TEST"


def test_create_source_rejects_invalid_type(wg_env, fresh_modules):
    import directory_store as ds

    with pytest.raises(ValueError):
        ds.create_source("Bad", "not_a_type", {"host": "x", "base_dn": "y"})


def test_resolve_secret_reads_env_var_never_config(wg_env, fresh_modules, monkeypatch):
    import directory_store as ds

    sid = ds.create_source("AD Test", "ldap_ad", {"host": "ad.local", "base_dn": "dc=test"}, secret_env_var="AD_BIND_PASSWORD_UNITTEST")
    row = ds.get_source(sid)
    assert "AD_BIND_PASSWORD_UNITTEST" not in row["config_json"]  # jamais de secret dans la config

    monkeypatch.setenv("AD_BIND_PASSWORD_UNITTEST", "s3cr3t")
    assert ds.resolve_secret(row) == "s3cr3t"


def test_record_test_result_updates_source(wg_env, fresh_modules):
    import directory_store as ds

    sid = ds.create_source("AD Test", "ldap_ad", {"host": "ad.local", "base_dn": "dc=test"})
    ds.record_test_result(sid, False, "Connexion refusee")
    row = ds.get_source(sid)
    assert row["last_test_ok"] == 0
    assert row["last_test_error"] == "Connexion refusee"


def test_job_lifecycle_and_provisioning_map(wg_env, fresh_modules):
    import directory_store as ds

    sid = ds.create_source("AD Test", "ldap_ad", {"host": "x", "base_dn": "y"})
    job_id = ds.create_job(sid, "group", {"group": "VPN-Users"}, total=1, actor="admin")

    ds.update_job(job_id, status="running")
    ds.append_log(job_id, sid, "jdupont", "vpn-jdupont", "created", None, "admin", "group")
    ds.record_provisioning(sid, "jdupont", "vpn-jdupont", "admin", "group", job_id)
    ds.update_job(job_id, status="done", processed=1, succeeded=1)

    job = ds.get_job(job_id)
    assert job["status"] == "done"
    assert ds.get_provisioning_map(sid) == {"jdupont": "vpn-jdupont"}
    logs = ds.list_log_for_job(job_id)
    assert len(logs) == 1 and logs[0]["action"] == "created"


def test_delete_source_removes_it(wg_env, fresh_modules):
    import directory_store as ds

    sid = ds.create_source("Temp", "ldap_ad", {"host": "x", "base_dn": "y"})
    ds.delete_source(sid)
    assert ds.get_source(sid) is None


# --------------------------------------------------------------- provisioning.py

def _user(id_, name, email=None, disabled=False):
    from directory.base import DirectoryUser
    return DirectoryUser(id=id_, display_name=name, email=email, account_disabled=disabled)


def test_preview_creates_skips_disabled_and_detects_conflicts(wg_env, fresh_modules):
    import provisioning as prov

    users = [_user("jdupont", "Jean Dupont"), _user("msmith", "Marie Smith"), _user("old", "Old Account", disabled=True)]

    plan = prov.preview(users, existing_client_names=set(), already_mapped={}, options={"template": "{login}"})
    assert plan["stats"] == {"will_create": 2, "already_exists": 0, "disabled_skipped": 1, "conflict": 0, "invalid": 0}

    plan2 = prov.preview(users, existing_client_names={"msmith"}, already_mapped={}, options={"template": "{login}"})
    assert plan2["stats"]["conflict"] == 1
    assert plan2["stats"]["will_create"] == 1


def test_preview_flags_already_provisioned(wg_env, fresh_modules):
    import provisioning as prov

    users = [_user("jdupont", "Jean Dupont")]
    plan = prov.preview(users, existing_client_names=set(), already_mapped={"jdupont": "jdupont"}, options={})
    assert plan["stats"]["already_exists"] == 1
    assert plan["stats"]["will_create"] == 0


def test_build_client_name_sanitises_template_output(wg_env, fresh_modules):
    import provisioning as prov

    user = _user("j.dupont", "Jean Dupont")
    assert prov.build_client_name("vpn-{login}", user) == "vpn-j-dupont"


def test_run_job_creates_logs_and_handles_wgctl_failures(wg_env, fresh_modules):
    import directory_store as ds
    import provisioning as prov

    users = [_user("jdupont", "Jean Dupont", "j@x.com"), _user("msmith", "Marie Smith", "m@x.com")]
    sid = ds.create_source("Test", "ldap_ad", {"host": "x", "base_dn": "y"})
    job_id = ds.create_job(sid, "group", {"group": "VPN-Users"}, total=len(users), actor="admin")

    def fake_run_wgctl(action, **kwargs):
        if kwargs.get("name") == "msmith":
            raise Exception("simulated wgctl failure")
        return {"ok": True}

    prov.run_job(job_id, users, set(), {}, {"template": "{login}"}, "admin", sid, "group", fake_run_wgctl, ds)

    job = ds.get_job(job_id)
    assert job["status"] == "done"
    assert job["succeeded"] == 1
    assert job["failed"] == 1
    assert ds.get_provisioning_map(sid) == {"jdupont": "jdupont"}


def test_resolve_selection_manual_mode_fetches_each_user(wg_env, fresh_modules):
    import provisioning as prov

    class FakeConnector:
        def get_user(self, uid):
            return _user(uid, uid.title())

    users = prov.resolve_selection(FakeConnector(), "manual", {"user_ids": ["alice", "bob"]})
    assert [u.id for u in users] == ["alice", "bob"]


def test_resolve_selection_group_mode_requires_group(wg_env, fresh_modules):
    import provisioning as prov

    class FakeConnector:
        def get_group_members(self, group):
            return []

    with pytest.raises(ValueError, match="group"):
        prov.resolve_selection(FakeConnector(), "group", {})


# --------------------------------------------------------------- extensions (E1, E3, E7, E8, E9, E11)

def test_check_quota_raises_when_exceeded(wg_env, fresh_modules):
    import directory_store as ds
    import provisioning as prov

    sid = ds.create_source("Test", "ldap_ad", {"host": "x", "base_dn": "y"}, quota_max=2)
    src = ds.get_source(sid)
    prov.check_quota(src, 2)  # exactement au plafond : OK
    with pytest.raises(ValueError, match="Quota"):
        prov.check_quota(src, 3)


def test_check_quota_unlimited_when_no_max(wg_env, fresh_modules):
    import directory_store as ds
    import provisioning as prov

    sid = ds.create_source("Test", "ldap_ad", {"host": "x", "base_dn": "y"})
    prov.check_quota(ds.get_source(sid), 999999)  # ne doit pas lever


def test_compute_dynamic_tags_ignores_empty_placeholders(wg_env, fresh_modules):
    import provisioning as prov

    user = _user("jdupont", "Jean Dupont")
    user.department = "commercial"
    tags = prov.compute_dynamic_tags(user, ["ad-dept-{department}", "ad-title-{title}"])
    assert tags == ["ad-dept-commercial"]


def test_rollback_job_revokes_only_created_clients_of_that_job(wg_env, fresh_modules):
    import directory_store as ds
    import provisioning as prov

    sid = ds.create_source("Test", "ldap_ad", {"host": "x", "base_dn": "y"})
    job_id = ds.create_job(sid, "manual", {}, total=1, actor="admin")
    ds.append_log(job_id, sid, "jdupont", "jdupont", "created", None, "admin", "manual")
    ds.record_provisioning(sid, "jdupont", "jdupont", "admin", "manual", job_id)

    calls = []
    def fake_wgctl(action, **kwargs):
        calls.append((action, kwargs.get("name")))
        return {"ok": True}

    result = prov.rollback_job(job_id, sid, "admin", fake_wgctl, ds)
    assert result["revoked"] == ["jdupont"]
    assert ("revoke", "jdupont") in calls
    assert ds.get_provisioning_map(sid) == {}


def test_rollback_job_reports_failures_without_stopping(wg_env, fresh_modules):
    import directory_store as ds
    import provisioning as prov

    sid = ds.create_source("Test", "ldap_ad", {"host": "x", "base_dn": "y"})
    job_id = ds.create_job(sid, "manual", {}, total=2, actor="admin")
    ds.append_log(job_id, sid, "u1", "client1", "created", None, "admin", "manual")
    ds.append_log(job_id, sid, "u2", "client2", "created", None, "admin", "manual")

    def flaky_wgctl(action, **kwargs):
        if kwargs.get("name") == "client1":
            raise Exception("revoke failed")
        return {"ok": True}

    result = prov.rollback_job(job_id, sid, "admin", flaky_wgctl, ds)
    assert result["revoked"] == ["client2"]
    assert len(result["failed"]) == 1
    assert result["failed"][0]["client_name"] == "client1"


def test_run_sync_creates_new_entrants_up_to_max(wg_env, fresh_modules):
    import directory_store as ds
    import provisioning as prov

    sid = ds.create_source("Test", "ldap_ad", {"host": "x", "base_dn": "y"})
    users = [_user(f"u{i}", f"User {i}") for i in range(5)]
    calls = []
    def fake_wgctl(action, **kwargs):
        calls.append(kwargs.get("name"))
        return {"ok": True}

    diff = prov.run_sync(sid, None, {}, users, {"template": "{login}", "max_auto_provisions_per_run": 2}, "admin", fake_wgctl, ds)
    assert len(diff["added"]) == 2
    assert len(calls) == 2


def test_run_sync_disables_directory_disabled_accounts_never_revokes(wg_env, fresh_modules):
    import directory_store as ds
    import provisioning as prov

    sid = ds.create_source("Test", "ldap_ad", {"host": "x", "base_dn": "y"})
    mapped = {"olduser": "olduser-client"}
    current = [_user("olduser", "Old User", disabled=True)]
    calls = []
    def fake_wgctl(action, **kwargs):
        calls.append((action, kwargs.get("name")))
        return {"ok": True}

    diff = prov.run_sync(sid, None, mapped, current, {}, "admin", fake_wgctl, ds)
    assert diff["disabled"] == [{"user_id": "olduser", "client_name": "olduser-client"}]
    assert ("disable", "olduser-client") in calls
    assert not any(action == "revoke" for action, _ in calls)  # jamais de revocation automatique


def test_run_sync_marks_missing_users_as_orphans(wg_env, fresh_modules):
    import directory_store as ds
    import provisioning as prov

    sid = ds.create_source("Test", "ldap_ad", {"host": "x", "base_dn": "y"})
    ds.record_provisioning(sid, "gone", "gone-client", "admin", "manual")
    mapped = ds.get_provisioning_map(sid)
    diff = prov.run_sync(sid, None, mapped, [], {}, "admin", lambda *a, **k: {"ok": True}, ds)
    assert diff["orphaned"] == [{"user_id": "gone", "client_name": "gone-client"}]
    assert ds.list_orphans(sid)[0]["user_id"] == "gone"


def test_policy_lifecycle(wg_env, fresh_modules):
    import directory_store as ds

    sid = ds.create_source("Test", "ldap_ad", {"host": "x", "base_dn": "y"})
    pid = ds.create_policy(sid, "cn=VPN-Users,dc=test", "VPN Users Policy", template="vpn-{login}", expires_days=90, tags=["vip"])
    policies = ds.list_policies(sid)
    assert len(policies) == 1
    assert policies[0]["template"] == "vpn-{login}"

    fetched = ds.get_policy_for_group(sid, "cn=VPN-Users,dc=test")
    assert fetched["id"] == pid

    ds.delete_policy(pid)
    assert ds.list_policies(sid) == []


def test_reconcile_and_dissociate(wg_env, fresh_modules):
    import directory_store as ds

    sid = ds.create_source("Test", "ldap_ad", {"host": "x", "base_dn": "y"})
    ds.reconcile(sid, "jdupont", "existing-client", "admin")
    assert ds.get_provisioning_map(sid) == {"jdupont": "existing-client"}

    ds.dissociate_by_client_name("existing-client")
    assert ds.get_provisioning_map(sid) == {}


def test_sync_history_lifecycle(wg_env, fresh_modules):
    import directory_store as ds

    sid = ds.create_source("Test", "ldap_ad", {"host": "x", "base_dn": "y"})
    sync_id = ds.create_sync_history(sid)
    ds.finish_sync_history(sync_id, "done", added=3, disabled=1, diff={"added": ["a", "b", "c"]})
    history = ds.list_sync_history(sid)
    assert len(history) == 1
    assert history[0]["status"] == "done"
    assert history[0]["added"] == 3


def test_increment_quota_used(wg_env, fresh_modules):
    import directory_store as ds

    sid = ds.create_source("Test", "ldap_ad", {"host": "x", "base_dn": "y"}, quota_max=10)
    ds.increment_quota_used(sid, 3)
    ds.increment_quota_used(sid, 2)
    src = ds.get_source(sid)
    assert src["quota_used"] == 5
