#!/usr/bin/env python3
"""
BLOCKHash - directory/factory.py
=========================================================
Instancie le bon connecteur a partir du type d'une source enregistree
(table `directory_sources`, voir directory_store.py).

Types disponibles en Phase 1 (famille LDAP, voir ldap_connector.py) :
  ldap_ad, ldap_openldap, ldap_samba, ldap_freeipa, ldap_jumpcloud,
  ldap_google_secure, ldap_generic

Types sur la feuille de route (non implementes, voir README) :
  graph (Microsoft 365 / Entra ID via Microsoft Graph),
  google_workspace (Google Admin SDK Directory API)
"""

from .base import DirectoryConnectorError
from .google_connector import GoogleWorkspaceConnector
from .graph_connector import GraphConnector
from .ldap_connector import LdapConnector

# Types de source qui utilisent tous LdapConnector (seul `ad_mode` change
# le comportement par defaut : detection du bit ACCOUNTDISABLE et filtre
# utilisateur par defaut, voir ldap_connector.DEFAULT_USER_FILTER).
_LDAP_TYPES = {
    "ldap_ad": True,
    "ldap_samba": True,
    "ldap_azure_ad_ds": True,
    "ldap_openldap": False,
    "ldap_freeipa": False,
    "ldap_jumpcloud": False,
    "ldap_google_secure": False,
    "ldap_generic": False,
}

# Connecteurs API REST (voir graph_connector.py / google_connector.py).
_API_CONNECTORS = {
    "graph": GraphConnector,
    "google_workspace": GoogleWorkspaceConnector,
}


def get_connector(source_type: str, config: dict, bind_password: str):
    """`source_type` = valeur de `directory_sources.type`. `config` = dict
    deja parse de `config_json` (sans secret). `bind_password` = secret deja
    resolu par l'appelant (voir directory_store.resolve_secret) - pour les
    connecteurs LDAP c'est le mot de passe de bind, pour Graph le secret
    client ; ignore par GoogleWorkspaceConnector (voir sa docstring : le
    "secret" y est un chemin de fichier de cle de compte de service, deja
    dans `config`)."""
    if source_type in _API_CONNECTORS:
        return _API_CONNECTORS[source_type](config, bind_password)
    if source_type not in _LDAP_TYPES:
        raise DirectoryConnectorError(f"Type de source d'annuaire inconnu : {source_type!r}")

    cfg = dict(config)
    cfg.setdefault("ad_mode", _LDAP_TYPES[source_type])
    return LdapConnector(cfg, bind_password)


def supported_types() -> list:
    """Liste des types utilisables des maintenant (pour l'UI Sources)."""
    return sorted(list(_LDAP_TYPES.keys()) + list(_API_CONNECTORS.keys()))


def roadmap_types() -> dict:
    """Types annonces par le cahier des charges mais pas encore livres.
    Vide desormais : Graph et Google Workspace sont implementes (voir
    README, section Provisioning, pour l'etat des extensions E1-E15,
    qui restent elles sur la feuille de route)."""
    return {}
