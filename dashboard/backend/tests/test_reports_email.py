"""Test d'intégration bout-en-bout de l'envoi du rapport hebdomadaire par
e-mail : configure un vrai serveur SMTP local (aiosmtpd), configure le canal
e-mail via l'API comme le ferait un·e admin depuis la page Alertes, déclenche
l'envoi, et vérifie que l'e-mail a réellement été reçu avec le bon contenu.
Corrige un bug réel trouvé pendant ce test : la route renvoyait 200 même en
cas d'échec d'envoi (voir app.py:/api/reports/weekly-send)."""
import threading
import time

import pytest

aiosmtpd = pytest.importorskip("aiosmtpd.controller", reason="aiosmtpd non installé (dépendance de test uniquement)")


class _CollectingHandler:
    def __init__(self):
        self.received = []

    async def handle_DATA(self, server, session, envelope):
        self.received.append(
            {
                "mail_from": envelope.mail_from,
                "rcpt_tos": list(envelope.rcpt_tos),
                "content": envelope.content.decode("utf8", errors="replace"),
            }
        )
        return "250 Message accepted for delivery"


@pytest.fixture
def local_smtp_server():
    from aiosmtpd.controller import Controller

    handler = _CollectingHandler()
    controller = Controller(handler, hostname="127.0.0.1", port=1026)
    controller.start()
    time.sleep(0.2)
    yield handler
    controller.stop()


def get_client(wg_env, monkeypatch):
    from werkzeug.security import generate_password_hash

    monkeypatch.setenv("DASHBOARD_TOKEN", "legacytoken123")
    monkeypatch.setenv("DASHBOARD_USERNAME", "admin")
    monkeypatch.setenv("DASHBOARD_PASSWORD_HASH", generate_password_hash("adminpass123"))
    import app

    return app.app.test_client()


def test_weekly_report_actually_sends_email(wg_env, fresh_modules, monkeypatch, local_smtp_server):
    c = get_client(wg_env, monkeypatch)
    headers = {"X-API-Token": "legacytoken123"}

    # 1. Configuration du canal e-mail (equivalent de la page Alertes > Configurer les canaux)
    r = c.patch(
        "/api/alerts/config",
        json={"channels": {"email": {
            "enabled": True, "smtp_host": "127.0.0.1", "smtp_port": 1026, "use_tls": False,
            "smtp_user": "", "smtp_password": "", "from_addr": "blockhash@example.com", "to_addr": "ops@example.com",
        }}},
        headers=headers,
    )
    assert r.status_code == 200

    # 2. Activation du rapport hebdomadaire
    r = c.patch("/api/reports/weekly-config", json={"weekly_enabled": True, "to_addr": "ops@example.com"}, headers=headers)
    assert r.status_code == 200

    # 3. Declenchement de l'envoi
    r = c.post("/api/reports/weekly-send", headers=headers)
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["sent"] is True

    # 4. Verification que l'e-mail a REELLEMENT ete recu par le serveur SMTP
    time.sleep(0.3)
    assert len(local_smtp_server.received) == 1
    email = local_smtp_server.received[0]
    assert email["mail_from"] == "blockhash@example.com"
    assert "ops@example.com" in email["rcpt_tos"]
    assert "BLOCKHash" in email["content"]


def test_weekly_report_fails_clearly_without_smtp_config(wg_env, fresh_modules, monkeypatch):
    """Sans configuration SMTP, l'envoi doit echouer avec un code d'erreur
    HTTP et un message explicite - pas un 200 silencieux (c'est exactement
    le bug qui donnait l'impression que 'l'envoi ne fonctionne jamais')."""
    c = get_client(wg_env, monkeypatch)
    headers = {"X-API-Token": "legacytoken123"}

    c.patch("/api/reports/weekly-config", json={"weekly_enabled": True, "to_addr": "ops@example.com"}, headers=headers)
    r = c.post("/api/reports/weekly-send", headers=headers)

    assert r.status_code == 422
    body = r.get_json()
    assert body["sent"] is False
    assert "SMTP" in body["error"]


def test_pdf_export_produces_valid_pdf(wg_env, fresh_modules, monkeypatch):
    c = get_client(wg_env, monkeypatch)
    headers = {"X-API-Token": "legacytoken123"}
    r = c.post(
        "/api/reports/pdf",
        json={"title": "Test", "columns": ["A", "B"], "rows": [["1", "2"]]},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.data[:5] == b"%PDF-"
    assert r.headers["Content-Type"] == "application/pdf"
