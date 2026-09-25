"""Tests pour directory/google_connector.py (Google Workspace), avec
mock complet de l'Admin SDK (aucun domaine reel requis)."""

from unittest.mock import MagicMock, patch

import pytest


def test_missing_config_raises_clear_error(wg_env, fresh_modules):
    from directory.base import DirectoryConnectorError
    from directory.google_connector import GoogleWorkspaceConnector

    with pytest.raises(DirectoryConnectorError, match="incomplete"):
        GoogleWorkspaceConnector({"admin_email": "a@x.com"})  # service_account_key_path manquant


def test_list_users_maps_suspended_to_disabled(wg_env, fresh_modules):
    from directory.google_connector import GoogleWorkspaceConnector

    connector = GoogleWorkspaceConnector({"admin_email": "admin@x.com", "service_account_key_path": "/tmp/fake.json"})
    with patch.object(GoogleWorkspaceConnector, "_client") as mock_client:
        fake_svc = MagicMock()
        mock_client.return_value = fake_svc
        fake_svc.users.return_value.list.return_value.execute.return_value = {
            "users": [
                {"primaryEmail": "active@x.com", "name": {"fullName": "Active User"}, "suspended": False},
                {"primaryEmail": "susp@x.com", "name": {"fullName": "Suspended User"}, "suspended": True},
            ]
        }
        result = connector.list_users()
    by_id = {u.id: u for u in result.items}
    assert by_id["active@x.com"].account_disabled is False
    assert by_id["susp@x.com"].account_disabled is True


def test_list_groups_handles_missing_name_field(wg_env, fresh_modules):
    """Regression : dict.get(k, expr) evalue `expr` meme quand `k` est
    present, ce qui levait un KeyError si un groupe n'avait pas de champ
    email et un nom present - voir google_connector.py."""
    from directory.google_connector import GoogleWorkspaceConnector

    connector = GoogleWorkspaceConnector({"admin_email": "admin@x.com", "service_account_key_path": "/tmp/fake.json"})
    with patch.object(GoogleWorkspaceConnector, "_client") as mock_client:
        fake_svc = MagicMock()
        mock_client.return_value = fake_svc
        fake_svc.groups.return_value.list.return_value.execute.return_value = {
            "groups": [{"id": "g1", "name": "VPN-Users"}]  # pas de champ "email"
        }
        groups = connector.list_groups()
    assert groups[0].name == "VPN-Users"


def test_list_ous_handles_missing_name_field(wg_env, fresh_modules):
    from directory.google_connector import GoogleWorkspaceConnector

    connector = GoogleWorkspaceConnector({"admin_email": "admin@x.com", "service_account_key_path": "/tmp/fake.json"})
    with patch.object(GoogleWorkspaceConnector, "_client") as mock_client:
        fake_svc = MagicMock()
        mock_client.return_value = fake_svc
        fake_svc.orgunits.return_value.list.return_value.execute.return_value = {
            "organizationUnits": [{"orgUnitPath": "/Sales"}]  # pas de champ "name"
        }
        ous = connector.list_ous()
    assert ous[0].name == "/Sales"


def test_get_group_members_skips_non_user_and_deleted_members(wg_env, fresh_modules):
    from directory.base import DirectoryConnectorError
    from directory.google_connector import GoogleWorkspaceConnector

    connector = GoogleWorkspaceConnector({"admin_email": "admin@x.com", "service_account_key_path": "/tmp/fake.json"})
    with patch.object(GoogleWorkspaceConnector, "_client") as mock_client:
        fake_svc = MagicMock()
        mock_client.return_value = fake_svc
        fake_svc.members.return_value.list.return_value.execute.return_value = {
            "members": [{"id": "u1", "type": "USER"}, {"id": "grp1", "type": "GROUP"}, {"id": "u2", "type": "USER"}],
        }

        def fake_get_user(user_id):
            if user_id == "u2":
                raise DirectoryConnectorError("deleted")
            from directory.base import DirectoryUser
            return DirectoryUser(id=user_id, display_name=user_id)

        with patch.object(GoogleWorkspaceConnector, "get_user", side_effect=fake_get_user):
            members = connector.get_group_members("g1")
    assert len(members) == 1
    assert members[0].id == "u1"
