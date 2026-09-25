# -*- coding: utf-8 -*-
"""Comptes multi-utilisateurs, rôles et tokens API scopés (items 49/52).

Remplace le modèle précédent (un seul compte admin + un seul token partagé
DASHBOARD_TOKEN) par :
- une table `users` (nom d'utilisateur, hash de mot de passe, rôle) ;
- des tokens de SESSION propres à chaque connexion (créés par /api/login,
  stockés hachés en base, jamais en clair) ;
- des tokens API long-lived, nommés, avec un scope et une expiration
  optionnelle, gérés indépendamment des comptes utilisateurs (item 52).

Compatibilité ascendante : DASHBOARD_TOKEN (l'ancien jeton statique partagé)
continue de fonctionner comme jeton "admin" implicite - indispensable pour
ne pas casser des scripts d'automatisation existants pendant la transition.
Il est toutefois clairement marqué comme obsolète dans l'UI (voir Réglages
> Tokens API) et peut être désactivé en le retirant de dashboard.env une
fois la migration terminée.

Hiérarchie des rôles (du plus faible au plus fort) :
- reader   : lecture seule (consultation de toutes les pages).
- operator : reader + gestion des clients (ajout/edition/desactivation/
  revocation/import), marquage des alertes comme lues/archivees.
- admin    : operator + operations systeme (sauvegardes, restauration,
  rotation de cles, redemarrage du tunnel, purge, reglages globaux,
  gestion des comptes et des tokens API).
"""
import hashlib
import os
import secrets
from datetime import datetime, timezone

from werkzeug.security import check_password_hash, generate_password_hash

import store

ROLE_RANK = {"reader": 0, "operator": 1, "admin": 2}
VALID_ROLES = tuple(ROLE_RANK.keys())

SESSION_TTL_SECONDS = int(os.environ.get("DASHBOARD_SESSION_TTL_SECONDS", str(30 * 86400)))  # 30 jours

# Prefixes/chemins qui exigent le role admin, quelle que soit la methode HTTP
# (operations systeme sensibles : sauvegardes, rotation de cles, reglages
# globaux, gestion des comptes/tokens...). Tout le reste suit la regle par
# defaut : GET -> reader, sinon -> operator (voir required_role_for ci-dessous).
ADMIN_ONLY_PREFIXES = (
    "/api/system",
    "/api/users",
    "/api/tokens",
    "/api/reports/weekly-config",
    "/api/reports/weekly-send",
    "/api/push/test",
    "/api/directory",
    "/api/provision",
)
ADMIN_ONLY_EXACT_PATCH = {"/api/alerts/config", "/api/compliance/policies", "/api/settings"}


def required_role_for(method, path):
    """Regle grossiere mais centralisee (un seul endroit a auditer) plutot
    que d'annoter individuellement ~80 routes Flask. Documentee comme limite
    connue : quelques routes pourraient meriter un role plus fin au cas par
    cas (voir discussion GDPR export), mais ce decoupage reader/operator/
    admin couvre honnetement l'essentiel du besoin exprime."""
    if path == "/api/bug-reports" and method == "POST":
        return "reader"  # n'importe quel compte peut signaler un bug
    if path.startswith("/api/bug-reports"):
        return "admin"  # consulter/traiter la boite de reception reste reserve aux admins
    if any(path.startswith(p) for p in ADMIN_ONLY_PREFIXES):
        return "admin"
    if method == "PATCH" and path in ADMIN_ONLY_EXACT_PATCH:
        return "admin"
    if method == "GET":
        return "reader"
    return "operator"


def hash_token(raw_token):
    """SHA-256 : les tokens de session/API ne sont JAMAIS stockes en clair,
    seulement leur empreinte (meme principe qu'un mot de passe, mais pas
    besoin du cout bcrypt/scrypt ici car un token est deja une chaine
    aleatoire a haute entropie, pas un secret choisi par un humain)."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_raw_token(prefix):
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def ensure_bootstrap_admin(dashboard_username, dashboard_password_hash):
    """Migration : si la table `users` est vide et qu'un compte legacy est
    configure via dashboard.env, on l'importe tel quel comme premier compte
    admin - condition necessaire pour que la personne qui a deja configure
    le dashboard ne se retrouve jamais bloquee dehors apres cette mise a
    jour. N'ecrase jamais un utilisateur existant."""
    if store.list_users():
        return
    if not dashboard_username or not dashboard_password_hash:
        return
    store.create_user(dashboard_username, dashboard_password_hash, "admin")


def authenticate(username, password):
    """Verifie (nom d'utilisateur, mot de passe) contre la table `users`.
    Renvoie le dict utilisateur (sans le hash) si valide, None sinon."""
    user = store.get_user(username)
    if not user or not user["active"]:
        return None
    try:
        if not check_password_hash(user["password_hash"], password):
            return None
    except ValueError:
        return None
    return {"username": user["username"], "role": user["role"]}


def create_session_token(username):
    raw = generate_raw_token("sess")
    store.create_session(hash_token(raw), username, SESSION_TTL_SECONDS)
    return raw


def resolve_session_token(raw_token):
    row = store.get_session(hash_token(raw_token))
    if not row:
        return None
    user = store.get_user(row["username"])
    if not user or not user["active"]:
        return None
    return {"username": user["username"], "role": user["role"]}


def resolve_api_token(raw_token):
    row = store.get_api_token(hash_token(raw_token))
    if not row:
        return None
    store.touch_api_token(row["token_hash"])
    return {"username": f"token:{row['name']}", "role": row["scope"]}


def create_password_hash(password):
    return generate_password_hash(password)
