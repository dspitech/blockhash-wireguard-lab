"""Tests pour directory/graph_connector.py (Microsoft 365 / Entra ID),
avec mock complet de MSAL et des appels HTTP (aucun tenant reel requis)."""

from unittest.mock import MagicMock, patch

import pytest


def _connector():
    from directory.graph_connector import GraphConnector
    return GraphConnector({"tenant_id": "t1", "client_id": "c1"}, "secret123")


def test_missing_config_raises_clear_error(wg_env, fresh_modules):
    from directory.base import DirectoryConnectorError
    from directory.graph_connector import GraphConnector

    with pytest.raises(DirectoryConnectorError, match="incomplete"):
        GraphConnector({"tenant_id": "t1"}, "secret")  # client_id manquant


def test_test_connection_success(wg_env, fresh_modules):
    connector = _connector()
    with patch("msal.ConfidentialClientApplication") as MockApp:
        MockApp.return_value.acquire_token_for_client.return_value = {"access_token": "tok", "expires_in": 3600}
        with patch("requests.request") as mock_req:
            resp = MagicMock(status_code=200, ok=True, text='{"displayName":"Contoso"}')
            resp.json.return_value = {"displayName": "Contoso"}
            mock_req.return_value = resp
            result = connector.test_connection()
    assert result["ok"] is True


def test_authentication_failure_gives_clear_message(wg_env, fresh_modules):
    connector = _connector()
    with patch("msal.ConfidentialClientApplication") as MockApp:
        MockApp.return_value.acquire_token_for_client.return_value = {"error": "invalid_client", "error_description": "bad secret"}
        result = connector.test_connection()
    assert result["ok"] is False
    assert "bad secret" in result["detail"]


@pytest.mark.parametrize("status,expected_fragment", [
    (401, "authentification refusee"),
    (403, "permissions"),
    (429, "limite de debit"),
])
def test_http_error_codes_give_actionable_messages(wg_env, fresh_modules, status, expected_fragment):
    connector = _connector()
    with patch("msal.ConfidentialClientApplication") as MockApp:
        MockApp.return_value.acquire_token_for_client.return_value = {"access_token": "tok", "expires_in": 3600}
        with patch("requests.request") as mock_req:
            resp = MagicMock(status_code=status, ok=False, text="error")
            mock_req.return_value = resp
            result = connector.test_connection()
    assert result["ok"] is False
    assert expected_fragment.lower() in result["detail"].lower()


def test_list_users_paginates_via_odata_nextlink(wg_env, fresh_modules):
    connector = _connector()
    with patch("msal.ConfidentialClientApplication") as MockApp:
        MockApp.return_value.acquire_token_for_client.return_value = {"access_token": "tok", "expires_in": 3600}
        with patch("requests.request") as mock_req:
            page1 = MagicMock(status_code=200, ok=True, text="x")
            page1.json.return_value = {
                "value": [{"userPrincipalName": "a@x.com", "displayName": "A", "accountEnabled": True}],
                "@odata.nextLink": "https://graph.microsoft.com/v1.0/users?skiptoken=abc",
                "@odata.count": 2,
            }
            page2 = MagicMock(status_code=200, ok=True, text="x")
            page2.json.return_value = {"value": [{"userPrincipalName": "b@x.com", "displayName": "B", "accountEnabled": False}]}
            mock_req.side_effect = [page1, page2]
            result = connector.list_users(page=2, page_size=1)
    assert result.items[0].id == "b@x.com"
    assert result.items[0].account_disabled is True
    assert result.total == 2


def test_list_ous_returns_empty_documented_limitation(wg_env, fresh_modules):
    """Microsoft Graph n'expose pas d'API generique de navigation par OU
    pour un tenant cloud-only - voir docstring du connecteur."""
    connector = _connector()
    assert connector.list_ous() == []


def test_get_ou_members_raises_clear_error(wg_env, fresh_modules):
    from directory.base import DirectoryConnectorError
    connector = _connector()
    with pytest.raises(DirectoryConnectorError, match="unite d'organisation"):
        connector.get_ou_members("some-ou")
