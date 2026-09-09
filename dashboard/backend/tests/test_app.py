"""Tests pour app.py (endpoints Flask, via le test client)."""
from conftest import add_peer


def get_client(wg_env):
    import app

    return app.app.test_client()


def test_healthz_ok(wg_env, fresh_modules):
    c = get_client(wg_env)
    r = c.get("/healthz")
    assert r.status_code == 200
    assert r.get_json()["status"] == "ok"


def test_version_endpoint(wg_env, fresh_modules):
    c = get_client(wg_env)
    r = c.get("/api/version")
    assert r.status_code == 200
    body = r.get_json()
    assert "version" in body
    assert body["client_management_enabled"] is False


def test_overview_shape(wg_env, fresh_modules):
    add_peer(wg_env["wg_conf"], "alice", "ALICEPUB0000000000000000000000000000000000=", "10.66.66.5/32")
    c = get_client(wg_env)
    r = c.get("/api/overview")
    assert r.status_code == 200
    body = r.get_json()
    for key in ("stats", "peers", "logs", "throughput_series", "client_management_enabled"):
        assert key in body
    assert body["stats"]["total_peers"] == 1


def test_logs_pagination_endpoint(wg_env, fresh_modules):
    import store

    store.ingest_log_snapshot(
        1000, "ALICEPUB0000000000000000000000000000000000=\tpsk\t1.2.3.4:51820\t10.0.0.5/32\t1000\t100\t50\t25"
    )
    store.ingest_log_snapshot(
        1300, "ALICEPUB0000000000000000000000000000000000=\tpsk\t1.2.3.4:51820\t10.0.0.5/32\t1300\t200\t100\t25"
    )

    c = get_client(wg_env)
    r = c.get("/api/logs?limit=1&offset=0")
    assert r.status_code == 200
    body = r.get_json()
    assert body["total"] == 2
    assert len(body["rows"]) == 1


def test_client_management_disabled_returns_403(wg_env, fresh_modules):
    c = get_client(wg_env)
    r = c.post("/api/clients", json={"name": "test"})
    assert r.status_code == 403


def test_system_ops_disabled_returns_403(wg_env, fresh_modules):
    c = get_client(wg_env)
    r = c.get("/api/system/backups")
    assert r.status_code == 403


def test_invalid_client_name_rejected(wg_env, fresh_modules, monkeypatch):
    monkeypatch.setenv("CLIENT_MANAGEMENT_ENABLED", "true")
    import app

    c = app.app.test_client()
    r = c.post("/api/clients", json={"name": "invalid name with spaces!"})
    assert r.status_code == 422


def test_compliance_lists_never_connected_client(wg_env, fresh_modules):
    add_peer(wg_env["wg_conf"], "old-client", "OLDPUB00000000000000000000000000000000000=", "10.66.66.7/32")
    c = get_client(wg_env)
    r = c.get("/api/compliance")
    assert r.status_code == 200
    names = [entry["name"] for entry in r.get_json()["clients"]]
    assert "old-client" in names


def test_alerts_dedup_endpoints(wg_env, fresh_modules):
    import store

    store.should_send("inactive:SOMEPUBKEY", 86400)
    c = get_client(wg_env)

    r = c.get("/api/alerts/dedup")
    assert r.status_code == 200
    assert len(r.get_json()) == 1

    r = c.delete("/api/alerts/dedup/inactive:SOMEPUBKEY")
    assert r.status_code == 200

    r = c.get("/api/alerts/dedup")
    assert r.get_json() == []


def test_logs_endpoint_status_filter_combines_with_pagination(wg_env, fresh_modules):
    import time
    import store

    add_peer(wg_env["wg_conf"], "alice", "ALICEPUB0000000000000000000000000000000000=", "10.66.66.5/32")
    add_peer(wg_env["wg_conf"], "bruno", "BRUNOPUB0000000000000000000000000000000000=", "10.66.66.6/32")

    now = int(time.time())
    # alice: recent handshake (online). bruno: no live handshake (never).
    fake_wg = wg_env["bin_dir"] / "wg"
    fake_wg.write_text(
        "#!/usr/bin/env bash\n"
        "if [ \"$1\" = \"show\" ]; then\n"
        "  echo wg0\n"
        f"  echo -e \"ALICEPUB0000000000000000000000000000000000=\\tpsk\\t1.2.3.4:51820\\t10.66.66.5/32\\t{now}\\t1000\\t500\\t25\"\n"
        "fi\n"
    )
    fake_wg.chmod(0o755)

    for i in range(5):
        ts = now - (5 - i) * 300
        store.ingest_log_snapshot(
            ts,
            f"ALICEPUB0000000000000000000000000000000000=\tpsk\t1.2.3.4:51820\t10.66.66.5/32\t{ts}\t100\t50\t25\n"
            f"BRUNOPUB0000000000000000000000000000000000=\tpsk\t9.9.9.9:51820\t10.66.66.6/32\t{ts}\t200\t100\t25",
        )

    import app

    c = app.app.test_client()
    r = c.get("/api/logs?status=online&limit=100")
    assert r.status_code == 200
    body = r.get_json()
    assert body["total"] == 5  # seules les 5 lignes d'alice (online)
    assert all(row["peer"] == "alice" for row in body["rows"])

    r_never = c.get("/api/logs?status=never&limit=100")
    assert r_never.get_json()["total"] == 5
    assert all(row["peer"] == "bruno" for row in r_never.get_json()["rows"])
