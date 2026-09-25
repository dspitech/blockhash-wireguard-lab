#!/usr/bin/env python3
"""
BLOCKHash - directory/ldap_connector.py
=========================================================
Connecteur LDAP generique : couvre toute source qui parle LDAP(S), soit
la grande majorite des annuaires d'entreprise (voir README, section
"Provisioning VPN depuis un annuaire") :
  - Active Directory local (LDAPS)               -> type "ldap_ad"
  - Azure AD Domain Services (LDAPS)              -> type "ldap_ad"
  - OpenLDAP                                       -> type "ldap_generic"
  - Samba AD DC                                    -> type "ldap_ad"
  - FreeIPA / Red Hat IdM                          -> type "ldap_generic"
  - JumpCloud (LDAP standard)                      -> type "ldap_generic"
  - Google Secure LDAP                             -> type "ldap_generic"

Un seul connecteur pour toutes ces sources car elles partagent le meme
protocole ; seuls le filtre utilisateur par defaut et la detection des
comptes desactives different legerement selon que la source est "de
type AD" (bit ACCOUNTDISABLE de userAccountControl) ou non (voir
`_is_disabled`).

Securite (voir README, section securite du module provisioning) :
  - LDAPS ou StartTLS obligatoire (`test_connection` refuse le LDAP en
    clair sauf `allow_plaintext=True` explicite, pense pour un labo).
  - Toute valeur injectee dans un filtre LDAP passe par
    `ldap3.utils.conv.escape_filter_chars` (protection anti-injection
    LDAP, voir tests test_ldap_connector.py::test_search_escapes_filter).
  - Le mot de passe de bind n'est jamais lu depuis `config_json` : il
    est toujours resolu via une variable d'environnement (voir
    directory_store.py et README section configuration).
"""

from ldap3 import ALL, SIMPLE, SUBTREE, Connection, Server, Tls
from ldap3.core.exceptions import LDAPException
from ldap3.utils.conv import escape_filter_chars

from .base import DirectoryConnector, DirectoryConnectorError, DirectoryGroup, DirectoryOU, DirectoryUser, PaginatedResult

# Filtres par defaut : type "ldap_ad" (Active Directory et compatibles) vs
# "ldap_generic" (OpenLDAP/FreeIPA/JumpCloud/Google Secure LDAP...).
DEFAULT_USER_FILTER = {
    "ldap_ad": "(&(objectCategory=person)(objectClass=user))",
    "ldap_generic": "(objectClass=inetOrgPerson)",
}
DEFAULT_GROUP_FILTER = {
    "ldap_ad": "(objectClass=group)",
    "ldap_generic": "(objectClass=groupOfNames)",
}
DEFAULT_OU_FILTER = "(objectClass=organizationalUnit)"

# ACCOUNTDISABLE = bit 2 de userAccountControl (UF_ACCOUNTDISABLE, doc Microsoft)
UAC_ACCOUNTDISABLE = 0x0002


class LdapConnector(DirectoryConnector):
    def __init__(self, config: dict, bind_password: str):
        """`config` = contenu (deja parse) de `directory_sources.config_json`
        (jamais de secret dedans, voir module docstring). `bind_password`
        est resolu a part par l'appelant (directory_store.resolve_secret),
        depuis la variable d'environnement referencee par `secret_ref`."""
        self.config = config
        self.bind_password = bind_password
        self.family = "ldap_ad" if config.get("ad_mode", True) else "ldap_generic"

        self.host = config["host"]
        self.port = int(config.get("port") or (636 if config.get("use_ssl", True) else 389))
        self.use_ssl = bool(config.get("use_ssl", True))
        self.start_tls = bool(config.get("start_tls", False))
        self.bind_dn = config.get("bind_dn") or ""
        self.base_dn = config["base_dn"]
        self.user_filter = config.get("user_filter") or DEFAULT_USER_FILTER[self.family]
        self.group_filter = config.get("group_filter") or DEFAULT_GROUP_FILTER[self.family]
        self.ou_filter = config.get("ou_filter") or DEFAULT_OU_FILTER
        self.allow_plaintext = bool(config.get("allow_plaintext", False))

        # Mapping d'attributs (personnalisable, cf. extension E13 de la
        # feuille de route pour un mapping libre supplementaire).
        attrs = config.get("attributes") or {}
        self.attr_login = attrs.get("login", "sAMAccountName" if self.family == "ldap_ad" else "uid")
        self.attr_name = attrs.get("name", "displayName" if self.family == "ldap_ad" else "cn")
        self.attr_email = attrs.get("email", "mail")
        self.attr_phone = attrs.get("phone", "telephoneNumber")
        self.attr_dept = attrs.get("department", "department")
        self.attr_title = attrs.get("title", "title")
        self.attr_location = attrs.get("location", "physicalDeliveryOfficeName")
        self.attr_language = attrs.get("language", "preferredLanguage")
        self.attr_uac = "userAccountControl" if self.family == "ldap_ad" else None

        if not self.use_ssl and not self.start_tls and not self.allow_plaintext:
            raise DirectoryConnectorError(
                "Connexion LDAP en clair refusee (TLS obligatoire) - activez use_ssl ou start_tls, "
                "ou allow_plaintext=true explicitement pour un usage labo uniquement."
            )

    # ------------------------------------------------------------- interne
    def _connection(self):
        tls = Tls(validate=__import__("ssl").CERT_REQUIRED) if (self.use_ssl or self.start_tls) else None
        server = Server(self.host, port=self.port, use_ssl=self.use_ssl, get_info=ALL, tls=tls)
        try:
            conn = Connection(
                server,
                user=self.bind_dn or None,
                password=self.bind_password or None,
                authentication=SIMPLE if self.bind_dn else None,
                auto_bind=False,
                receive_timeout=10,
            )
            if self.start_tls and not self.use_ssl:
                conn.start_tls()
            if not conn.bind():
                raise DirectoryConnectorError(f"Echec du bind LDAP : {conn.result.get('description', 'raison inconnue')}")
        except LDAPException as exc:
            raise DirectoryConnectorError(f"Connexion LDAP impossible ({self.host}:{self.port}) : {exc}") from exc
        return conn

    @staticmethod
    def _esc(value: str) -> str:
        """Echappe systematiquement toute valeur injectee dans un filtre LDAP
        (protection anti-injection, voir module docstring et tests)."""
        return escape_filter_chars(str(value))

    def _is_disabled(self, entry) -> bool:
        if self.attr_uac and self.attr_uac in entry:
            try:
                uac = int(entry[self.attr_uac].value)
                return bool(uac & UAC_ACCOUNTDISABLE)
            except (TypeError, ValueError):
                return False
        # Sources non-AD : pas de bit standard, on considere actif par
        # defaut sauf mapping explicite (attributes.disabled_attr) - hors
        # perimetre Phase 1, documente dans la feuille de route (voir README).
        return False

    def _entry_to_user(self, entry) -> DirectoryUser:
        def g(attr):
            try:
                v = entry[attr].value
                return str(v) if v else None
            except Exception:
                return None

        return DirectoryUser(
            id=g(self.attr_login) or str(entry.entry_dn),
            display_name=g(self.attr_name) or g(self.attr_login) or str(entry.entry_dn),
            email=g(self.attr_email),
            phone=g(self.attr_phone),
            department=g(self.attr_dept),
            title=g(self.attr_title),
            location=g(self.attr_location),
            language=g(self.attr_language),
            account_disabled=self._is_disabled(entry),
            dn=str(entry.entry_dn),
            raw={a: g(a) for a in (self.attr_login, self.attr_name, self.attr_email, self.attr_phone,
                                     self.attr_dept, self.attr_title, self.attr_location, self.attr_language) if g(a)},
        )

    def _attr_list(self):
        attrs = [self.attr_login, self.attr_name, self.attr_email, self.attr_phone,
                 self.attr_dept, self.attr_title, self.attr_location, self.attr_language, "memberOf"]
        if self.attr_uac:
            attrs.append(self.attr_uac)
        return attrs

    # --------------------------------------------------------- interface
    def test_connection(self) -> dict:
        try:
            conn = self._connection()
            conn.unbind()
            return {"ok": True, "detail": f"Connexion et bind reussis sur {self.host}:{self.port}."}
        except DirectoryConnectorError as exc:
            return {"ok": False, "detail": str(exc)}

    def list_groups(self, search: str = "") -> list:
        conn = self._connection()
        try:
            filt = self.group_filter
            if search:
                filt = f"(&{filt}(cn=*{self._esc(search)}*))"
            conn.search(self.base_dn, filt, search_scope=SUBTREE, attributes=["cn", "member"])
            groups = []
            for e in conn.entries:
                member_count = None
                try:
                    member_count = len(e["member"].values)
                except Exception:
                    pass
                groups.append(DirectoryGroup(id=str(e.entry_dn), name=str(e["cn"].value), member_count=member_count, dn=str(e.entry_dn)))
            return groups
        finally:
            conn.unbind()

    def list_ous(self) -> list:
        conn = self._connection()
        try:
            conn.search(self.base_dn, self.ou_filter, search_scope=SUBTREE, attributes=["ou"])
            return [DirectoryOU(id=str(e.entry_dn), name=str(e["ou"].value) if "ou" in e else str(e.entry_dn), dn=str(e.entry_dn)) for e in conn.entries]
        finally:
            conn.unbind()

    def list_users(self, group=None, ou=None, search=None, page=1, page_size=50) -> PaginatedResult:
        conn = self._connection()
        try:
            filt = self.user_filter
            if search:
                term = self._esc(search)
                filt = f"(&{filt}(|({self.attr_login}=*{term}*)({self.attr_name}=*{term}*)({self.attr_email}=*{term}*)))"
            if group:
                filt = f"(&{filt}(memberOf={self._esc(group)}))"
            search_base = ou if ou else self.base_dn

            entries = list(conn.extend.standard.paged_search(
                search_base=search_base,
                search_filter=filt,
                search_scope=SUBTREE,
                attributes=self._attr_list(),
                paged_size=500,
                generator=True,
            ))
            total = len(entries)
            start = max(0, (page - 1) * page_size)
            page_entries = entries[start:start + page_size]

            users = []
            for raw in page_entries:
                if raw.get("type") != "searchResEntry":
                    continue
                attrs = raw.get("attributes", {})
                users.append(self._raw_to_user(raw.get("dn", ""), attrs))
            return PaginatedResult(items=users, total=total, page=page, page_size=page_size)
        finally:
            conn.unbind()

    def _raw_to_user(self, dn: str, attrs: dict) -> DirectoryUser:
        def g(name):
            v = attrs.get(name)
            if isinstance(v, list):
                return str(v[0]) if v else None
            return str(v) if v else None

        disabled = False
        if self.attr_uac and attrs.get(self.attr_uac):
            try:
                raw_uac = attrs[self.attr_uac]
                uac_val = int(raw_uac[0] if isinstance(raw_uac, list) else raw_uac)
                disabled = bool(uac_val & UAC_ACCOUNTDISABLE)
            except (TypeError, ValueError, IndexError):
                pass

        return DirectoryUser(
            id=g(self.attr_login) or dn,
            display_name=g(self.attr_name) or g(self.attr_login) or dn,
            email=g(self.attr_email),
            phone=g(self.attr_phone),
            department=g(self.attr_dept),
            title=g(self.attr_title),
            location=g(self.attr_location),
            language=g(self.attr_language),
            account_disabled=disabled,
            dn=dn,
            groups=[str(x) for x in attrs.get("memberOf", [])] if attrs.get("memberOf") else [],
        )

    def get_user(self, user_id: str) -> DirectoryUser:
        conn = self._connection()
        try:
            filt = f"(&{self.user_filter}({self.attr_login}={self._esc(user_id)}))"
            conn.search(self.base_dn, filt, search_scope=SUBTREE, attributes=self._attr_list())
            if not conn.entries:
                raise DirectoryConnectorError(f"Utilisateur introuvable : {user_id}")
            return self._entry_to_user(conn.entries[0])
        finally:
            conn.unbind()

    def get_group_members(self, group_id: str) -> list:
        # group_id est le DN du groupe (voir list_groups) - deja une valeur
        # de confiance issue de l'annuaire, mais echappee quand meme par
        # coherence/defense en profondeur.
        return self.list_users(group=group_id, page=1, page_size=100000).items

    def get_ou_members(self, ou_id: str) -> list:
        return self.list_users(ou=ou_id, page=1, page_size=100000).items
