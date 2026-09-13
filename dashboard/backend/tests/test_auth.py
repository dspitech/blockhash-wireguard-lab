"""Tests pour l'authentification multi-utilisateurs, les roles et les
tokens API (items 49/52). Reprend le flux verifie manuellement pendant le
developpement (login, permissions par role, retro-compatibilite du jeton
legacy, protection du dernier compte admin)."""
from werkzeug.security import generate_password_hash


def get_client(wg_env, monkeypatch):
    monkeypatch.setenv("DASHBOARD_TOKEN", "legacytoken123")
    monkeypatch.setenv("DASHBOARD_USERNAME", "admin")
    monkeypatch.setenv("DASHBOARD_PASSWORD_HASH", generate_password_hash("adminpass123"))
    import app

    return app.app.test_client()


def login(client, username, password):
    r = client.post("/api/login", json={"username": username, "password": password})
    return r


def test_bootstrap_admin_login_succeeds(wg_env, fresh_modules, monkeypatch):
    c = get_client(wg_env, monkeypatch)
    r = login(c, "admin", "adminpass123")
    assert r.status_code == 200
    assert r.get_json()["role"] == "admin"


def test_wrong_password_rejected(wg_env, fresh_modules, monkeypatch):
    c = get_client(wg_env, monkeypatch)
    r = login(c, "admin", "wrong")
    assert r.status_code == 401


def test_legacy_token_still_works(wg_env, fresh_modules, monkeypatch):
    c = get_client(wg_env, monkeypatch)
    r = c.get("/api/auth/me", headers={"X-API-Token": "legacytoken123"})
    assert r.status_code == 200
    assert r.get_json()["role"] == "admin"


def test_reader_cannot_write_or_access_system(wg_env, fresh_modules, monkeypatch):
    c = get_client(wg_env, monkeypatch)
    admin_token = login(c, "admin", "adminpass123").get_json()["token"]

    r = c.post(
        "/api/users",
        json={"username": "reader1", "password": "readerpass1", "role": "reader"},
        headers={"X-API-Token": admin_token},
    )
    assert r.status_code == 201

    reader_token = login(c, "reader1", "readerpass1").get_json()["token"]

    r = c.get("/api/clients", headers={"X-API-Token": reader_token})
    assert r.status_code == 200

    r = c.post("/api/clients", json={"name": "test1"}, headers={"X-API-Token": reader_token})
    assert r.status_code == 403
    assert r.get_json()["error"] == "insufficient_role"

    r = c.get("/api/system/backups", headers={"X-API-Token": reader_token})
    assert r.status_code == 403


def test_cannot_delete_last_active_admin(wg_env, fresh_modules, monkeypatch):
    c = get_client(wg_env, monkeypatch)
    admin_token = login(c, "admin", "adminpass123").get_json()["token"]

    # Un second admin existe : on doit pouvoir retrograder/supprimer le premier.
    c.post(
        "/api/users",
        json={"username": "admin2", "password": "adminpass456", "role": "admin"},
        headers={"X-API-Token": admin_token},
    )
    r = c.patch("/api/users/admin", json={"role": "reader"}, headers={"X-API-Token": admin_token})
    assert r.status_code == 200

    # Plus qu'un seul admin actif (admin2) : impossible de le retrograder/supprimer.
    admin2_token = login(c, "admin2", "adminpass456").get_json()["token"]
    r = c.patch("/api/users/admin2", json={"role": "reader"}, headers={"X-API-Token": admin2_token})
    assert r.status_code == 422


def test_api_token_scope_enforced(wg_env, fresh_modules, monkeypatch):
    c = get_client(wg_env, monkeypatch)
    admin_token = login(c, "admin", "adminpass123").get_json()["token"]

    r = c.post(
        "/api/tokens",
        json={"name": "ci-script", "scope": "operator"},
        headers={"X-API-Token": admin_token},
    )
    assert r.status_code == 201
    api_token = r.get_json()["token"]

    r = c.get("/api/auth/me", headers={"X-API-Token": api_token})
    assert r.get_json()["role"] == "operator"

    r = c.get("/api/system/backups", headers={"X-API-Token": api_token})
    assert r.status_code == 403


def test_revoked_api_token_rejected(wg_env, fresh_modules, monkeypatch):
    c = get_client(wg_env, monkeypatch)
    admin_token = login(c, "admin", "adminpass123").get_json()["token"]

    r = c.post("/api/tokens", json={"name": "temp", "scope": "reader"}, headers={"X-API-Token": admin_token})
    api_token = r.get_json()["token"]
    tokens = c.get("/api/tokens", headers={"X-API-Token": admin_token}).get_json()
    rowid = next(t["rowid"] for t in tokens if t["name"] == "temp")

    r = c.delete(f"/api/tokens/{rowid}", headers={"X-API-Token": admin_token})
    assert r.status_code == 200

    r = c.get("/api/auth/me", headers={"X-API-Token": api_token})
    assert r.status_code == 401
