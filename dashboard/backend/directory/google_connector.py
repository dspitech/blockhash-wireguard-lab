#!/usr/bin/env python3
"""
BLOCKHash - directory/google_connector.py
=========================================================
Connecteur Google Workspace via l'Admin SDK Directory API, authentifie
par un compte de service avec delegation de domaine (impersonation
d'un compte administrateur du domaine, requis par l'API Directory).

Difference volontaire avec les autres connecteurs (LDAP : mot de passe
de bind ; Graph : secret client) concernant la gestion du secret : la
cle d'un compte de service Google est un fichier JSON multi-champs
(project_id, private_key, client_email...), pas une simple chaine. On
stocke donc dans `config_json` un **chemin de fichier**
(`service_account_key_path`, ex: /etc/blockhash/secrets/google-sa.json)
plutot qu'un nom de variable d'environnement - le fichier lui-meme
reste hors du controle de version et avec des permissions restrictives
(0600, meme logique que les cles WireGuard - voir README section
securite), mais son CONTENU n'est jamais recopie dans la base SQLite.

Permissions requises cote Google Workspace : le compte de service doit
avoir la delegation de domaine activee, avec les scopes
`admin.directory.user.readonly` et `admin.directory.group.readonly`
autorises dans la console d'administration Google Workspace, et
`admin_email` doit etre un compte disposant des droits d'administration
de l'annuaire (l'API Directory ne peut etre appelee qu'en tant
qu'utilisateur imite ayant ces droits).
"""

from .base import DirectoryConnector, DirectoryConnectorError, DirectoryGroup, DirectoryOU, DirectoryUser, PaginatedResult

SCOPES = [
    "https://www.googleapis.com/auth/admin.directory.user.readonly",
    "https://www.googleapis.com/auth/admin.directory.group.readonly",
    "https://www.googleapis.com/auth/admin.directory.orgunit.readonly",
]


class GoogleWorkspaceConnector(DirectoryConnector):
    def __init__(self, config: dict, _unused_secret: str = ""):
        self.admin_email = config.get("admin_email")
        self.key_path = config.get("service_account_key_path")
        self.customer_id = config.get("customer_id", "my_customer")
        if not (self.admin_email and self.key_path):
            raise DirectoryConnectorError(
                "Configuration Google Workspace incomplete : 'admin_email' et "
                "'service_account_key_path' sont obligatoires."
            )
        self._service = None

    # ------------------------------------------------------------- interne
    def _client(self):
        if self._service is not None:
            return self._service
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
            from googleapiclient.errors import HttpError  # noqa: F401 - importe pour valider la dependance
        except ImportError as exc:
            raise DirectoryConnectorError(
                "Les paquets 'google-api-python-client' et 'google-auth' ne sont pas installes (requirements.txt)."
            ) from exc
        try:
            creds = service_account.Credentials.from_service_account_file(self.key_path, scopes=SCOPES)
            creds = creds.with_subject(self.admin_email)
            self._service = build("admin", "directory_v1", credentials=creds, cache_discovery=False)
        except FileNotFoundError as exc:
            raise DirectoryConnectorError(f"Fichier de cle de compte de service introuvable : {self.key_path}") from exc
        except Exception as exc:  # noqa: BLE001 - erreurs google-auth heterogenes, on les uniformise
            raise DirectoryConnectorError(f"Authentification Google Workspace impossible : {exc}") from exc
        return self._service

    def _call(self, request):
        from googleapiclient.errors import HttpError
        try:
            return request.execute()
        except HttpError as exc:
            status = getattr(exc.resp, "status", None)
            if status == 403:
                raise DirectoryConnectorError(
                    "Google Workspace : acces refuse (403) - verifiez la delegation de domaine et les scopes "
                    "autorises pour ce compte de service dans la console d'administration."
                ) from exc
            raise DirectoryConnectorError(f"Google Workspace a renvoye une erreur ({status}) : {exc}") from exc

    @staticmethod
    def _google_user_to_domain(u: dict) -> DirectoryUser:
        name = u.get("name", {})
        phones = u.get("phones") or []
        orgs = u.get("organizations") or [{}]
        return DirectoryUser(
            id=u.get("primaryEmail") or u.get("id"),
            display_name=name.get("fullName") or u.get("primaryEmail"),
            email=u.get("primaryEmail"),
            phone=(phones[0].get("value") if phones else None),
            department=orgs[0].get("department") if orgs else None,
            title=orgs[0].get("title") if orgs else None,
            location=u.get("orgUnitPath"),
            language=u.get("languages", [{}])[0].get("languageCode") if u.get("languages") else None,
            account_disabled=bool(u.get("suspended", False)),
            dn=None,
            raw=u,
        )

    # --------------------------------------------------------- interface
    def test_connection(self) -> dict:
        try:
            svc = self._client()
            self._call(svc.users().list(customer=self.customer_id, maxResults=1))
            return {"ok": True, "detail": "Authentification et appel Google Admin SDK reussis."}
        except DirectoryConnectorError as exc:
            return {"ok": False, "detail": str(exc)}

    def list_groups(self, search: str = "") -> list:
        svc = self._client()
        kwargs = {"customer": self.customer_id}
        if search:
            kwargs["query"] = f"name:{search}*"
        data = self._call(svc.groups().list(**kwargs))
        return [DirectoryGroup(id=g["id"], name=g.get("name") or g.get("email", g["id"]), member_count=g.get("directMembersCount")) for g in data.get("groups", [])]

    def list_ous(self) -> list:
        svc = self._client()
        data = self._call(svc.orgunits().list(customerId=self.customer_id, type="all"))
        return [DirectoryOU(id=ou["orgUnitPath"], name=ou.get("name") or ou["orgUnitPath"], dn=ou["orgUnitPath"]) for ou in data.get("organizationUnits", [])]

    def list_users(self, group=None, ou=None, search=None, page=1, page_size=50) -> PaginatedResult:
        if group:
            return PaginatedResult(items=self.get_group_members(group), total=None, page=1, page_size=page_size)
        svc = self._client()
        kwargs = {"customer": self.customer_id, "maxResults": min(page_size, 500)}
        query_parts = []
        if search:
            query_parts.append(f"email:{search}* OR givenName:{search}* OR familyName:{search}*")
        if ou:
            query_parts.append(f"orgUnitPath='{ou}'")
        if query_parts:
            kwargs["query"] = " ".join(query_parts)

        data = self._call(svc.users().list(**kwargs))
        current_page = 1
        while current_page < page and data.get("nextPageToken"):
            kwargs["pageToken"] = data["nextPageToken"]
            data = self._call(svc.users().list(**kwargs))
            current_page += 1

        items = [self._google_user_to_domain(u) for u in data.get("users", [])]
        return PaginatedResult(items=items, total=len(items), page=page, page_size=page_size)

    def get_user(self, user_id: str) -> DirectoryUser:
        svc = self._client()
        data = self._call(svc.users().get(userKey=user_id))
        return self._google_user_to_domain(data)

    def get_group_members(self, group_id: str) -> list:
        svc = self._client()
        members, page_token = [], None
        while True:
            kwargs = {"groupKey": group_id, "maxResults": 200}
            if page_token:
                kwargs["pageToken"] = page_token
            data = self._call(svc.members().list(**kwargs))
            for m in data.get("members", []):
                if m.get("type") != "USER":
                    continue
                try:
                    members.append(self.get_user(m["id"]))
                except DirectoryConnectorError:
                    continue  # membre externe/supprime : ignore plutot que d'echouer tout le lot
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return members

    def get_ou_members(self, ou_id: str) -> list:
        return self.list_users(ou=ou_id, page=1, page_size=500).items
