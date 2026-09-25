#!/usr/bin/env python3
"""
BLOCKHash - directory/graph_connector.py
=========================================================
Connecteur Microsoft 365 / Entra ID via Microsoft Graph (API REST),
authentification "client credentials" (application, pas utilisateur)
via MSAL. Permissions d'application requises, consentement admin :
  User.Read.All, Group.Read.All

Limitation documentee (propre a Microsoft Graph, pas a BLOCKHash) :
Graph n'expose pas de notion generique d'"unite d'organisation" pour un
tenant cloud-only (les OU sont un concept Active Directory on-premise ;
en environnement hybride avec Azure AD Connect, l'information existe
cote attribut `onPremisesDistinguishedName` mais Graph ne fournit pas
d'endpoint de navigation par OU). `list_ous`/`get_ou_members` renvoient
donc une liste vide avec un message explicite plutot que d'echouer
silencieusement - voir README section "Provisioning VPN depuis un
annuaire" pour cette limitation.

Pagination : Graph utilise un curseur opaque (`@odata.nextLink`), pas
un `page`/`page_size` classique. Ce connecteur simule une pagination
par page/page_size en parcourant les pages Graph successives jusqu'a
atteindre la page demandee - correct mais O(page) requetes HTTP pour
une page profonde ; suffisant pour l'usage interactif de l'explorateur,
documente comme limite connue pour de tres gros tenants (>10 pages).
"""

import time

import requests

from .base import DirectoryConnector, DirectoryConnectorError, DirectoryGroup, DirectoryOU, DirectoryUser, PaginatedResult

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
AUTHORITY_BASE = "https://login.microsoftonline.com"
SCOPE = ["https://graph.microsoft.com/.default"]

USER_SELECT = (
    "id,userPrincipalName,displayName,mail,mobilePhone,businessPhones,department,"
    "jobTitle,officeLocation,preferredLanguage,accountEnabled"
)


class GraphConnector(DirectoryConnector):
    def __init__(self, config: dict, client_secret: str):
        self.tenant_id = config.get("tenant_id")
        self.client_id = config.get("client_id")
        self.client_secret = client_secret
        if not (self.tenant_id and self.client_id and self.client_secret):
            raise DirectoryConnectorError(
                "Configuration Microsoft Graph incomplete : tenant_id, client_id et le secret client "
                "(variable d'environnement referencee par secret_env_var) sont obligatoires."
            )
        self._token = None
        self._token_expires_at = 0

    # ------------------------------------------------------------- interne
    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token
        try:
            import msal
        except ImportError as exc:
            raise DirectoryConnectorError("Le paquet 'msal' n'est pas installe (requirements.txt).") from exc

        app = msal.ConfidentialClientApplication(
            self.client_id,
            authority=f"{AUTHORITY_BASE}/{self.tenant_id}",
            client_credential=self.client_secret,
        )
        result = app.acquire_token_for_client(scopes=SCOPE)
        if "access_token" not in result:
            desc = result.get("error_description", result.get("error", "erreur inconnue"))
            raise DirectoryConnectorError(f"Authentification Microsoft Graph refusee : {desc}")
        self._token = result["access_token"]
        self._token_expires_at = time.time() + int(result.get("expires_in", 3600))
        return self._token

    def _request(self, method: str, url_or_path: str, **kwargs) -> dict:
        url = url_or_path if url_or_path.startswith("http") else f"{GRAPH_BASE}{url_or_path}"
        headers = {"Authorization": f"Bearer {self._get_token()}", "ConsistencyLevel": "eventual"}
        try:
            resp = requests.request(method, url, headers=headers, timeout=15, **kwargs)
        except requests.RequestException as exc:
            raise DirectoryConnectorError(f"Microsoft Graph injoignable : {exc}") from exc
        if resp.status_code == 401:
            raise DirectoryConnectorError("Microsoft Graph : authentification refusee (401) - verifiez client_id/secret/tenant_id.")
        if resp.status_code == 403:
            raise DirectoryConnectorError(
                "Microsoft Graph : acces refuse (403) - verifiez que les permissions d'application "
                "User.Read.All et Group.Read.All ont ete accordees ET consenties par un administrateur du tenant."
            )
        if resp.status_code == 429:
            raise DirectoryConnectorError("Microsoft Graph : limite de debit atteinte (429), reessayez plus tard.")
        if not resp.ok:
            raise DirectoryConnectorError(f"Microsoft Graph a renvoye une erreur ({resp.status_code}) : {resp.text[:300]}")
        return resp.json() if resp.text else {}

    @staticmethod
    def _graph_user_to_domain(u: dict) -> DirectoryUser:
        phone = u.get("mobilePhone") or (u.get("businessPhones") or [None])[0]
        return DirectoryUser(
            id=u.get("userPrincipalName") or u.get("id"),
            display_name=u.get("displayName") or u.get("userPrincipalName") or u.get("id"),
            email=u.get("mail") or u.get("userPrincipalName"),
            phone=phone,
            department=u.get("department"),
            title=u.get("jobTitle"),
            location=u.get("officeLocation"),
            language=u.get("preferredLanguage"),
            account_disabled=(u.get("accountEnabled") is False),
            dn=None,
            raw=u,
        )

    # --------------------------------------------------------- interface
    def test_connection(self) -> dict:
        try:
            self._request("GET", "/organization?$select=displayName,id")
            return {"ok": True, "detail": "Authentification et appel Microsoft Graph reussis."}
        except DirectoryConnectorError as exc:
            return {"ok": False, "detail": str(exc)}

    def list_groups(self, search: str = "") -> list:
        path = "/groups?$select=id,displayName"
        if search:
            path += f"&$search=\"displayName:{search}\""
        data = self._request("GET", path)
        groups = []
        for g in data.get("value", []):
            groups.append(DirectoryGroup(id=g["id"], name=g.get("displayName", g["id"])))
        return groups

    def list_ous(self) -> list:
        # Voir docstring du module : non applicable a un tenant Entra ID cloud-only.
        return []

    def list_users(self, group=None, ou=None, search=None, page=1, page_size=50) -> PaginatedResult:
        if ou:
            raise DirectoryConnectorError(
                "La selection par unite d'organisation (OU) n'est pas disponible pour une source "
                "Microsoft Graph (concept propre a Active Directory on-premise, voir README)."
            )
        if group:
            return self._list_group_members_paginated(group, page, page_size)

        path = f"/users?$select={USER_SELECT}&$top={min(page_size, 999)}&$count=true"
        if search:
            term = search.replace('"', '')
            path += f"&$search=\"displayName:{term}\" OR \"mail:{term}\" OR \"userPrincipalName:{term}\""
            path += "&$orderby=displayName"

        # Graph pagine par curseur opaque : on avance page par page jusqu'a
        # atteindre celle demandee (voir docstring du module).
        data = self._request("GET", path)
        current_page = 1
        total = data.get("@odata.count")
        while current_page < page and "@odata.nextLink" in data:
            data = self._request("GET", data["@odata.nextLink"])
            current_page += 1

        items = [self._graph_user_to_domain(u) for u in data.get("value", [])]
        return PaginatedResult(items=items, total=total if total is not None else len(items), page=page, page_size=page_size)

    def _list_group_members_paginated(self, group_id, page, page_size):
        data = self._request("GET", f"/groups/{group_id}/members?$select={USER_SELECT}&$top={min(page_size, 999)}")
        current_page = 1
        while current_page < page and "@odata.nextLink" in data:
            data = self._request("GET", data["@odata.nextLink"])
            current_page += 1
        items = [self._graph_user_to_domain(u) for u in data.get("value", []) if u.get("@odata.type", "").endswith("user") or "userPrincipalName" in u]
        return PaginatedResult(items=items, total=len(items), page=page, page_size=page_size)

    def get_user(self, user_id: str) -> DirectoryUser:
        data = self._request("GET", f"/users/{user_id}?$select={USER_SELECT}")
        return self._graph_user_to_domain(data)

    def get_group_members(self, group_id: str) -> list:
        users, page = [], 1
        while True:
            result = self._list_group_members_paginated(group_id, page, 999)
            users.extend(result.items)
            if len(result.items) < 999:
                break
            page += 1
        return users

    def get_ou_members(self, ou_id: str) -> list:
        raise DirectoryConnectorError(
            "La selection par unite d'organisation (OU) n'est pas disponible pour une source "
            "Microsoft Graph (voir README)."
        )
