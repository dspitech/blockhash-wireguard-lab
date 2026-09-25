#!/usr/bin/env python3
"""
BLOCKHash - directory/base.py
=========================================================
Interface abstraite commune a tous les connecteurs d'annuaire. Tout le
code de provisioning (recherche, apercu, execution) ne connait que
cette interface, jamais un connecteur concret : c'est ce qui permet
d'ajouter un nouveau type de source (Microsoft Graph, Google Workspace,
Okta...) sans toucher au reste du module.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class DirectoryUser:
    """Utilisateur normalise, quelle que soit la source d'origine."""
    id: str                      # identifiant stable cote source (sAMAccountName, objectGUID, id Graph...)
    display_name: str
    email: str = None
    phone: str = None
    department: str = None
    title: str = None
    location: str = None
    language: str = None
    account_disabled: bool = False
    groups: list = field(default_factory=list)   # noms ou DN de groupes
    dn: str = None                # DN LDAP, absent pour les connecteurs API REST
    raw: dict = field(default_factory=dict)       # attributs bruts (pour mapping d'attributs personnalises, E13)


@dataclass
class DirectoryGroup:
    id: str
    name: str
    member_count: int = None
    dn: str = None


@dataclass
class DirectoryOU:
    id: str
    name: str
    dn: str = None
    parent_id: str = None


@dataclass
class PaginatedResult:
    items: list
    total: int
    page: int
    page_size: int


class DirectoryConnectorError(Exception):
    """Erreur remontee par un connecteur (connexion, authentification,
    timeout, filtre invalide...). Toujours porteuse d'un message adapte
    a un affichage direct dans le dashboard (jamais de trace brute)."""


class DirectoryConnector(ABC):
    """Interface que tout connecteur concret doit implementer. Voir
    ldap_connector.py pour l'implementation de reference (famille LDAP)."""

    @abstractmethod
    def test_connection(self) -> dict:
        """Retourne {"ok": bool, "detail": str} - jamais d'exception pour
        un simple echec de connexion, uniquement pour un appel mal forme."""

    @abstractmethod
    def list_groups(self, search: str = "") -> list:
        """-> list[DirectoryGroup]"""

    @abstractmethod
    def list_ous(self) -> list:
        """-> list[DirectoryOU]"""

    @abstractmethod
    def list_users(self, group=None, ou=None, search=None, page=1, page_size=50) -> PaginatedResult:
        """Recherche paginee. `group`/`ou` sont des id de DirectoryGroup/DirectoryOU
        (mutuellement exclusifs avec un usage typique), `search` un terme libre."""

    @abstractmethod
    def get_user(self, user_id: str) -> DirectoryUser:
        ...

    @abstractmethod
    def get_group_members(self, group_id: str) -> list:
        """-> list[DirectoryUser]"""

    @abstractmethod
    def get_ou_members(self, ou_id: str) -> list:
        """-> list[DirectoryUser]"""
