"""Tests pour directory/ (connecteur LDAP, factory, protection anti-injection)."""

import pytest


def test_factory_rejects_unknown_type(wg_env, fresh_modules):
    from directory.base import DirectoryConnectorError
    from directory.factory import get_connector

    with pytest.raises(DirectoryConnectorError, match="inconnu"):
        get_connector("not_a_real_type", {"host": "x"}, "pw")


def test_factory_supported_types_lists_all_connector_families(wg_env, fresh_modules):
    from directory.factory import supported_types

    types = supported_types()
    assert "ldap_ad" in types
    assert "ldap_openldap" in types
    assert "graph" in types
    assert "google_workspace" in types


def test_factory_instantiates_graph_connector(wg_env, fresh_modules):
    from directory.factory import get_connector
    from directory.graph_connector import GraphConnector

    connector = get_connector("graph", {"tenant_id": "t1", "client_id": "c1"}, "secret")
    assert isinstance(connector, GraphConnector)


def test_factory_instantiates_google_workspace_connector(wg_env, fresh_modules):
    from directory.factory import get_connector
    from directory.google_connector import GoogleWorkspaceConnector

    connector = get_connector("google_workspace", {"admin_email": "a@x.com", "service_account_key_path": "/tmp/x.json"}, "")
    assert isinstance(connector, GoogleWorkspaceConnector)


def test_ldap_connector_refuses_plaintext_without_explicit_opt_in(wg_env, fresh_modules):
    from directory.base import DirectoryConnectorError
    from directory.ldap_connector import LdapConnector

    with pytest.raises(DirectoryConnectorError, match="TLS obligatoire"):
        LdapConnector({"host": "ldap.local", "base_dn": "dc=test", "use_ssl": False, "start_tls": False}, "pw")


def test_ldap_connector_allows_plaintext_when_explicitly_opted_in(wg_env, fresh_modules):
    from directory.ldap_connector import LdapConnector

    connector = LdapConnector(
        {"host": "ldap.local", "base_dn": "dc=test", "use_ssl": False, "start_tls": False, "allow_plaintext": True},
        "pw",
    )
    assert connector.use_ssl is False


def test_escape_filter_chars_neutralises_ldap_injection(wg_env, fresh_modules):
    from directory.ldap_connector import LdapConnector

    payload = "*)(uid=*))(|(uid=*"
    escaped = LdapConnector._esc(payload)
    # Aucun metacaractere LDAP ne doit survivre non-echappe
    for char in ("*", "(", ")"):
        assert char not in escaped.replace(f"\\{ord(char):02x}", "")


def test_ldap_connector_against_mock_server_lists_users_and_detects_disabled(wg_env, fresh_modules):
    """Test d'integration contre un serveur LDAP en memoire (ldap3.MOCK_SYNC),
    sans dependance a un annuaire reel - couvre la recherche, la pagination
    et la detection du bit ACCOUNTDISABLE (AD)."""
    from ldap3 import Connection, MOCK_SYNC, Server

    from directory.ldap_connector import LdapConnector

    server = Server("mock-server")
    conn = Connection(server, user="cn=admin,dc=test", password="pw", client_strategy=MOCK_SYNC)
    conn.strategy.add_entry("cn=admin,dc=test", {"userPassword": "pw"})
    conn.strategy.add_entry("cn=jdupont,ou=users,dc=test", {
        "objectClass": ["user", "person"],
        "sAMAccountName": "jdupont",
        "displayName": "Jean Dupont",
        "mail": "jean.dupont@test.local",
        "userAccountControl": 512,
    })
    conn.strategy.add_entry("cn=disableduser,ou=users,dc=test", {
        "objectClass": ["user", "person"],
        "sAMAccountName": "disableduser",
        "displayName": "Disabled User",
        "mail": "disabled@test.local",
        "userAccountControl": 514,  # 512 | ACCOUNTDISABLE
    })
    conn.bind()

    connector = LdapConnector.__new__(LdapConnector)
    connector.config = {}
    connector.bind_password = "pw"
    connector.family = "ldap_ad"
    connector.host = "mock"
    connector.port = 636
    connector.use_ssl = True
    connector.start_tls = False
    connector.bind_dn = "cn=admin,dc=test"
    connector.base_dn = "dc=test"
    connector.user_filter = "(objectClass=user)"
    connector.group_filter = "(objectClass=group)"
    connector.ou_filter = "(objectClass=organizationalUnit)"
    connector.allow_plaintext = False
    connector.attr_login = "sAMAccountName"
    connector.attr_name = "displayName"
    connector.attr_email = "mail"
    connector.attr_phone = "telephoneNumber"
    connector.attr_dept = "department"
    connector.attr_title = "title"
    connector.attr_location = "physicalDeliveryOfficeName"
    connector.attr_language = "preferredLanguage"
    connector.attr_uac = "userAccountControl"
    connector._connection = lambda: conn

    result = connector.list_users(page=1, page_size=50)
    assert result.total == 2

    by_id = {u.id: u for u in result.items}
    assert by_id["jdupont"].account_disabled is False
    assert by_id["jdupont"].email == "jean.dupont@test.local"
    assert by_id["disableduser"].account_disabled is True
