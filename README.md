<div align="center">

# BLOCKHash

### Plateforme de supervision et d'administration WireGuard de niveau entreprise

Infrastructure-as-Code · Console d'administration web · Sécurité par conception · Multi-utilisateurs

[![License: MIT](https://img.shields.io/badge/License-MIT-informational.svg)](./LICENSE)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![WireGuard](https://img.shields.io/badge/WireGuard-Kernel%20module-88C0D0)
![Terraform](https://img.shields.io/badge/Terraform-Azure-844FBA)
![Status](https://img.shields.io/badge/Status-Production--ready%20lab-success)

</div>

---

## À propos de ce document

Ce README est la documentation de référence du projet **BLOCKHash** : une plateforme de supervision et d'administration WireGuard, avec sa console web, son infrastructure Terraform et ses scripts de déploiement. Il couvre :

- L'architecture du système, composant par composant ;
- La structure du dépôt et la stack technique ;
- Le déploiement, du provisionnement Azure à la validation ;
- L'intégralité des fonctionnalités de la plateforme ;
- Le modèle de sécurité et le guide de durcissement ;
- L'exploitation courante (sauvegardes, mises à jour, supervision) ;
- Le dépannage des incidents les plus courants.

---

## Sommaire

**Partie I : Qu'est-ce que BLOCKHash**

1. [Présentation générale](#1-présentation-générale)
2. [Proposition de valeur](#2-proposition-de-valeur)
3. [Ce que BLOCKHash n'est pas](#3-ce-que-blockhash-nest-pas)

**Partie II : Architecture**

4. [Vue d'ensemble de l'architecture](#4-vue-densemble-de-larchitecture)
5. [Composants du système](#5-composants-du-système)
6. [Flux réseau et ports](#6-flux-réseau-et-ports)
7. [Cycle de vie d'une connexion client](#7-cycle-de-vie-dune-connexion-client)
8. [Modèle de séparation des privilèges](#8-modèle-de-séparation-des-privilèges)

**Partie III : Stack technique**

9. [Infrastructure](#9-infrastructure)
10. [Système et réseau](#10-système-et-réseau)
11. [Backend](#11-backend)
12. [Frontend](#12-frontend)
13. [Dépendances complètes](#13-dépendances-complètes)

**Partie IV : Structure du projet**

14. [Vue d'ensemble de l'arborescence](#14-vue-densemble-de-larborescence)
15. [`terraform/`](#15-terraform)
16. [`scripts/`](#16-scripts)
17. [`dashboard/backend/`](#17-dashboardbackend)
18. [`dashboard/frontend/`](#18-dashboardfrontend)
19. [`dashboard/backend/tests/`](#19-dashboardbackendtests)

**Partie V : Déploiement**

20. [Prérequis](#20-prérequis)
21. [Étape 1 : Provisionner l'infrastructure Azure](#21-étape-1-provisionner-linfrastructure-azure)
22. [Étape 2 : Installer le serveur WireGuard](#22-étape-2-installer-le-serveur-wireguard)
23. [Étape 3 : Créer et distribuer des clients](#23-étape-3-créer-et-distribuer-des-clients)
24. [Étape 4 : Installer le dashboard BLOCKHash](#24-étape-4-installer-le-dashboard-blockhash)
25. [Étape 5 : Journalisation, monitoring et tâches planifiées](#25-étape-5-journalisation-monitoring-et-tâches-planifiées)
26. [Étape 6 : Valider le déploiement](#26-étape-6-valider-le-déploiement)

**Partie VI : Configuration de référence**

27. [Variables d'environnement](#27-variables-denvironnement)
28. [Fichiers de configuration persistés](#28-fichiers-de-configuration-persistés)
29. [Service systemd](#29-service-systemd)
30. [Reverse proxy Caddy](#30-reverse-proxy-caddy)
31. [Tâches planifiées (cron)](#31-tâches-planifiées-cron)

**Partie VII : Fonctionnalités**

32. [Vue d'ensemble (dashboard)](#32-vue-densemble-dashboard)
33. [Gestion des clients](#33-gestion-des-clients)
34. [Journal des connexions](#34-journal-des-connexions)
35. [Monitoring](#35-monitoring)
36. [Alertes](#36-alertes)
37. [Conformité](#37-conformité)
38. [Système](#38-système)
39. [Réglages](#39-réglages)
40. [Utilisateurs et rôles](#40-utilisateurs-et-rôles)
41. [Tokens API](#41-tokens-api)
42. [Aide intégrée](#42-aide-intégrée)
43. [Fonctionnalités transverses](#43-fonctionnalités-transverses)
44. [Provisioning VPN depuis un annuaire](#44-provisioning-vpn-depuis-un-annuaire)

**Partie VIII : Sécurité**

45. [Modèle d'authentification](#45-modèle-dauthentification)
46. [Contrôle d'accès par rôle (RBAC)](#46-contrôle-daccès-par-rôle-rbac)
47. [Protection des données et RGPD](#47-protection-des-données-et-rgpd)
48. [Traçabilité et audit](#48-traçabilité-et-audit)
49. [Checklist de durcissement](#49-checklist-de-durcissement)

**Partie IX : Référence API**

50. [Authentification des appels API](#50-authentification-des-appels-api)
51. [Catalogue des endpoints](#51-catalogue-des-endpoints)

**Partie X : Exploitation**

52. [Sauvegardes et rétention](#52-sauvegardes-et-rétention)
53. [Mise à jour de la plateforme](#53-mise-à-jour-de-la-plateforme)
54. [Supervision de la plateforme elle-même](#54-supervision-de-la-plateforme-elle-même)
55. [Capacité et dimensionnement](#55-capacité-et-dimensionnement)

**Partie XI : Dépannage**

56. [Méthodologie générale](#56-méthodologie-générale)
57. [Incidents courants](#57-incidents-courants)

**Partie XII : Limites connues et feuille de route**

58. [Hors périmètre assumé](#58-hors-périmètre-assumé)
59. [Feuille de route](#59-feuille-de-route)

**Annexes**

60. [Glossaire](#60-glossaire)
61. [Aide-mémoire des commandes](#61-aide-mémoire-des-commandes)
62. [Licence](#62-licence)

---

# Partie I : Qu'est-ce que BLOCKHash

## 1. Présentation générale

**BLOCKHash** est une plateforme complète qui transforme un serveur WireGuard « nu » en une **console d'administration VPN de niveau entreprise**. Le projet comprend deux couches indissociables :

1. **La couche infrastructure** : provisionnement Azure via Terraform, installation et durcissement du serveur WireGuard, scripts d'exploitation en ligne de commande.
2. **La couche applicative** : un dashboard web (backend Flask + frontend HTML/CSS/JS) qui pilote ce serveur WireGuard au travers d'une interface graphique complète : création et cycle de vie des clients, supervision temps réel, alerting, sauvegardes, conformité, comptes utilisateurs à rôles, tokens API, etc.

Le nom du projet reflète sa fonction : **BLOCK**ing/monitoring pour WireGuard, avec une architecture qui s'appuie fortement sur le **Hash**ing (jetons, mots de passe, intégrité des sauvegardes).

## 2. Proposition de valeur

WireGuard, pris isolément, est un protocole, pas une plateforme. Il ne fournit ni interface de gestion, ni notion d'utilisateur, ni journalisation exploitable, ni alerting, ni contrôle d'accès. BLOCKHash comble précisément ce vide :

| Besoin métier | Ce que WireGuard seul ne fournit pas | Ce que BLOCKHash ajoute |
|---|---|---|
| Onboarding/offboarding des utilisateurs | Édition manuelle de fichiers `.conf` | Création, import en masse, révocation en un clic, QR code |
| Visibilité opérationnelle | Rien (juste `wg show`) | Dashboard temps réel, graphiques de débit, carte GeoIP, heatmap |
| Alerting | Rien | Règles configurables (connexion, inactivité, hors-horaires...), envoi email/Slack/Discord/Telegram/Web Push |
| Traçabilité | Rien | Journal des connexions interrogeable, journal d'audit des actions admin |
| Reprise après incident | Sauvegarde manuelle du fichier `wg0.conf` | Sauvegardes versionnées, intègres (SHA-256), planifiées, restauration à double confirmation |
| Gouvernance des accès | Un seul secret partagé pour tout le monde | Comptes nominatifs, rôles (lecteur/opérateur/admin), tokens API scopés et révocables |
| Conformité | Rien | Politiques d'inactivité par tag, export RGPD par client, rapports PDF |

## 3. Ce que BLOCKHash n'est pas

Par souci de transparence (voir aussi la Partie XII) :

- **Ce n'est pas un fournisseur d'identité d'entreprise.** BLOCKHash gère ses propres comptes utilisateurs ; il ne s'intègre pas (encore) à un SSO/LDAP/Active Directory/OIDC externe.
- **Ce n'est pas une solution multi-tenant SaaS.** Le projet est conçu pour être déployé et exploité par une seule organisation, sur sa propre infrastructure.
- **Ce n'est pas un WAF ni un IDS/IPS.** La sécurité réseau périmétrique (NSG, pare-feu OS) reste de la responsabilité de l'infrastructure sous-jacente, documentée en Partie V.

---

# Partie II : Architecture

## 4. Vue d'ensemble de l'architecture

```
                                    Internet
                                        │
                    ┌───────────────────┼───────────────────┐
                    │ UDP 51820         │ TCP 443            │ TCP 22
                    │ (tunnel WireGuard)│ (dashboard, HTTPS) │ (SSH admin)
                    ▼                   ▼                    ▼
        ┌──────────────────────────────────────────────────────────────┐
        │              Azure NSG « nsg-wireguard-lab »                 │
        │   AllowWireGuard · AllowDashboard-Admin · AllowSSH-Admin ·    │
        │   DenyAllOtherInbound (règle « deny all » explicite)          │
        └──────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
        ┌──────────────────────────────────────────────────────────────┐
        │                VM Ubuntu (Standard_B2s par défaut)            │
        │                                                                │
        │   ┌────────────────┐        ┌─────────────────────────────┐  │
        │   │  Noyau Linux    │        │   Caddy (reverse proxy)      │  │
        │   │  module wireguard│       │   TLS interne, HTTP/2        │  │
        │   │  interface wg0   │◄──┐   │   /api/events/stream : flush │  │
        │   └────────────────┘    │   │   immédiat (SSE)              │  │
        │           ▲              │   └───────────┬─────────────────┘  │
        │           │ wg show      │                │ 127.0.0.1:8080     │
        │           │ (root only)  │                ▼                    │
        │   ┌───────┴────────┐    │   ┌─────────────────────────────┐  │
        │   │ wgctl.py         │◄──┘   │  Gunicorn (2 workers gevent) │  │
        │   │ wgops.py         │◄──────┤  Application Flask (app.py)  │  │
        │   │ (sudo -n, root)  │       │  73 routes API               │  │
        │   └──────────────────┘       └───────────┬─────────────────┘  │
        │                                            │                    │
        │   ┌────────────────────────────────────────┼─────────────┐    │
        │   │  /var/log/wireguard/blockhash.db (SQLite, 0660)       │    │
        │   │  /var/log/wireguard/audit.log                         │    │
        │   │  /etc/blockhash/*.json (réglages, alertes, rapports)  │    │
        │   │  /etc/wireguard/wg0.conf + backups/                   │    │
        │   └────────────────────────────────────────────────────────┘   │
        │                                                                │
        │   Cron : capture d'état (5 min) · purge (nuit) · alertes      │
        │   (5 min) · expirations (nuit) · sauvegardes planifiées       │
        └──────────────────────────────────────────────────────────────┘
```

## 5. Composants du système

| Composant | Rôle | Exécuté en tant que |
|---|---|---|
| **Module noyau `wireguard`** | Chiffrement/déchiffrement du trafic, gestion de l'interface `wg0` | Noyau (root) |
| **`wgctl.py`** | Logique privilégiée de gestion du cycle de vie des clients (ajout, activation, renommage, révocation, régénération de clés, contact/RGPD) | root, invoqué via `sudo -n` par www-data |
| **`wgops.py`** | Opérations système privilégiées (sauvegardes, restauration, rotation des clés serveur, redémarrage du tunnel, export, diagnostic) | root, invoqué via `sudo -n` par www-data |
| **`app.py` (Flask)** | API HTTP (73 routes), authentification, autorisation par rôle, orchestration | www-data, sans privilège root |
| **Gunicorn** | Serveur d'application WSGI, 2 workers en mode **gevent** (coroutines) | www-data |
| **Caddy** | Reverse proxy HTTPS, terminaison TLS, sert le frontend statique | root (bind sur le port 443), ou www-data selon le durcissement |
| **SQLite (`blockhash.db`)** | Persistance des métriques, logs de connexion, alertes, utilisateurs, sessions, tokens API, abonnements Web Push | Écrit par **www-data ET root** (voir §8) |
| **Cron (root)** | Capture périodique de l'état WireGuard, purge, évaluation des alertes, vérification des expirations, sauvegardes planifiées | root |

## 6. Flux réseau et ports

| Port | Protocole | Usage | Exposition |
|---|---|---|---|
| 51820 (configurable) | UDP | Tunnel WireGuard | Publique (Internet) |
| 443 | TCP | Dashboard (HTTPS via Caddy) | Publique, restreinte par NSG à l'IP admin si souhaité |
| 22 | TCP | SSH d'administration de la VM | Publique, restreinte par NSG à l'IP admin |
| 8080 | TCP | Gunicorn (backend Flask) | **Local uniquement** (`127.0.0.1`), jamais exposé directement |

## 7. Cycle de vie d'une connexion client

1. Le client WireGuard initie une poignée de main UDP vers l'`Endpoint` du serveur.
2. Le noyau Linux (module `wireguard`) authentifie et déchiffre les paquets suivants sans intervention applicative.
3. Toutes les 5 minutes, un script cron exécuté en root interroge `wg show wg0 dump`, calcule les deltas de trafic (octets reçus/émis depuis le dernier échantillon) et les insère dans `blockhash.db`.
4. Le flux **Server-Sent Events** (`/api/events/stream`) compare l'état courant à l'état précédent à chaque itération (toutes les 3 secondes) et pousse un événement `peer_connected`/`peer_disconnected` à tous les onglets ouverts dès qu'une transition est détectée.
5. Si une règle d'alerte correspond à la transition (ex. connexion hors horaires), une notification est déclenchée sur les canaux configurés (email, Slack, Discord, Telegram, Web Push).
6. L'historique de connexion reste consultable dans la page **Journal**, avec filtres, pagination et heatmap.

## 8. Modèle de séparation des privilèges

BLOCKHash applique le principe du **moindre privilège** de bout en bout :

- Le processus Flask (`app.py`) tourne **sans aucun privilège root**, sous l'utilisateur système `www-data`.
- Toute opération nécessitant un accès root (lecture de l'état WireGuard, écriture dans `/etc/wireguard/`, redémarrage du tunnel, rotation de clés) passe **exclusivement** par deux scripts dédiés, `wgctl.py` et `wgops.py`, invoqués via une règle `sudo -n` strictement scoped (pas de mot de passe interactif, pas d'accès shell).
- Un attaquant qui compromettrait le processus Flask n'obtient **pas** automatiquement un accès root : il est limité aux actions explicitement exposées par ces deux scripts, elles-mêmes validées côté Flask (nom de client, chemin de sauvegarde, etc.) avant l'appel privilégié.

> **Point d'attention opérationnel documenté :** certaines données (sessions utilisateur, comptes, tokens API, alertes) sont désormais écrites par **le processus www-data lui-même**, alors que la base SQLite historique n'était pensée que pour un écrivain root (le cron de capture). Le fichier est donc configuré en mode `0660` avec le bit **setgid** posé sur son répertoire parent, pour que les deux écrivains (root et www-data) y aient un accès garanti dans la durée. Voir Partie XI, [§57](#57-incidents-courants), pour le détail de cet arbitrage.

---

# Partie III : Stack technique

## 9. Infrastructure

| Technologie | Usage dans le projet |
|---|---|
| **Terraform** (>= 1.5) | Infrastructure-as-Code : provisionnement complet de l'environnement Azure (réseau, VM, NSG, disques) en modules réutilisables |
| **Microsoft Azure** | Fournisseur cloud cible (groupe de ressources, réseau virtuel, VM, IP publique) |
| **cloud-init** | Bootstrap de la VM à la création (fichier `cloud-init.yaml.tpl`), pour une configuration reproductible dès le premier démarrage |

## 10. Système et réseau

| Technologie | Usage |
|---|---|
| **Ubuntu 22.04 LTS** | Système d'exploitation de la VM |
| **WireGuard** (module noyau + `wireguard-tools`) | Cœur du VPN ([wireguard.com](https://www.wireguard.com/)) |
| **systemd** | Gestion du service `wg-quick@wg0` et du service `blockhash-dashboard` |
| **Caddy** | Reverse proxy HTTPS, terminaison TLS (certificat interne auto-signé), HTTP/2, gestion dédiée du flux SSE |
| **cron** | Orchestration des tâches périodiques (capture d'état, purge, alertes, expirations, sauvegardes planifiées) |
| **logrotate** | Rotation des journaux CSV/texte |
| **ufw / iptables** | Durcissement du pare-feu local, en complément du NSG Azure |

## 11. Backend

| Technologie | Version | Usage |
|---|---|---|
| **Python** | 3.10+ | Langage du backend |
| **Flask** | 3.0.3 | Framework web, 73 routes API REST |
| **Gunicorn** | 22.0.0 | Serveur WSGI de production |
| **gevent** | 24.2.1 | Worker asynchrone à base de coroutines : indispensable pour supporter de nombreuses connexions **Server-Sent Events** simultanées sans épuiser un pool de threads |
| **SQLite 3** (bibliothèque standard) | N/A | Persistance embarquée : métriques, logs, alertes, comptes, sessions, tokens, abonnements push : sans service de base de données externe à opérer |
| **Werkzeug (`security`)** | via Flask | Hachage des mots de passe (scrypt/pbkdf2 selon la version) |
| **pywebpush** | 2.5.0 | Envoi de notifications Web Push standard (RFC 8030), génération/gestion des clés VAPID |
| **psutil** | 6.0.0 | Métriques système (CPU, mémoire, disque, connexions TCP) |
| **fpdf2** | 2.7.9 | Génération de rapports PDF (conformité, audit) |

## 12. Frontend

| Technologie | Usage |
|---|---|
| **HTML5 / CSS3 / JavaScript vanilla (ES2020+)** | Aucun framework front (pas de React/Vue/Angular) : un unique fichier `app.js`, volontairement dépendance-minimale et vendorisé localement (aucun CDN externe requis en production) |
| **Chart.js** (vendorisé) | Graphiques de débit long terme |
| **chartjs-plugin-zoom** (vendorisé) | Zoom molette / pan par glisser sur les graphiques |
| **Leaflet** (vendorisé) | Carte de géolocalisation des endpoints clients (GeoIP) |
| **Service Worker (`sw.js`)** | Réception des notifications Web Push, y compris onglet fermé |
| **Web Push API / Notification API** | Alertes navigateur en temps réel |
| **Server-Sent Events (`EventSource`)** | Mise à jour temps réel du dashboard sans polling |
| **i18n maison** (`i18n/fr.json`, `i18n/en.json`) | Internationalisation FR/EN de l'interface statique |

## 13. Dépendances complètes

Fichier `dashboard/backend/requirements.txt` :

```
Flask==3.0.3
gunicorn==22.0.0
gevent==24.2.1
pywebpush==2.5.0
psutil==6.0.0
fpdf2==2.7.9
```

Aucune dépendance frontend n'est installée via un gestionnaire de paquets : les bibliothèques JS tierces (Chart.js, le plugin zoom, Leaflet) sont **vendorisées** (copiées localement dans `dashboard/frontend/js/vendor/`), afin que le dashboard reste pleinement fonctionnel même sur une infrastructure à accès Internet sortant restreint.

---

# Partie IV : Structure du projet

## 14. Vue d'ensemble de l'arborescence

```
blockhash-wireguard-lab/
├── LICENSE
├── README.md                        ← ce document
├── terraform/                       ← Infrastructure-as-Code (Azure)
│   ├── main.tf, variables.tf, providers.tf, outputs.tf
│   ├── terraform.tfvars.example
│   ├── deploy.ps1                   ← script de déploiement Windows/PowerShell
│   └── modules/
│       ├── network/                 ← VNet, subnet, NSG, IP publique
│       └── compute/                 ← VM, cloud-init, disque
├── scripts/                         ← Scripts d'exploitation (bash), à exécuter sur la VM
│   ├── 01-install-wireguard-server.sh
│   ├── 02-add-client.sh
│   ├── 03-install-dashboard.sh
│   ├── 04-logging-monitoring.sh
│   ├── 05-revoke-client.sh
│   ├── 06-manage-client.sh
│   ├── 07-check-expirations.sh
│   └── 09-check-alerts.sh
└── dashboard/
    ├── backend/                     ← API Flask (~5 360 lignes Python, 73 routes)
    │   ├── app.py                   ← point d'entrée, routes, auth, orchestration (1 642 lignes)
    │   ├── auth.py                  ← rôles, sessions, tokens API (135 lignes)
    │   ├── wgctl.py                 ← gestion privilégiée des clients (688 lignes)
    │   ├── wgops.py                 ← opérations système privilégiées (442 lignes)
    │   ├── wgstate.py               ← lecture d'état WireGuard, logs (269 lignes)
    │   ├── store.py                 ← couche SQLite (901 lignes)
    │   ├── alerts.py                ← moteur de règles d'alerte (445 lignes)
    │   ├── reports.py               ← génération PDF, rapport hebdomadaire (201 lignes)
    │   ├── webpush.py               ← notifications Web Push / VAPID (106 lignes)
    │   ├── geoip.py                 ← résolution géographique des endpoints (127 lignes)
    │   ├── system_monitor.py        ← métriques système (138 lignes)
    │   ├── anomalies.py             ← détection d'anomalies de débit (76 lignes)
    │   ├── settings_store.py        ← réglages persistés (73 lignes)
    │   ├── servers_store.py         ← registre multi-serveurs (116 lignes)
    │   ├── requirements.txt / requirements-dev.txt
    │   ├── pytest.ini
    │   └── tests/                   ← suite de tests (606 lignes, voir §19)
    └── frontend/                    ← interface web (HTML/CSS/JS vanilla)
        ├── index.html               ← squelette applicatif (SPA à sections)
        ├── sw.js                    ← service worker (Web Push)
        ├── js/
        │   ├── app.js                ← logique applicative complète
        │   ├── config.js             ← configuration runtime
        │   └── vendor/                ← bibliothèques tierces vendorisées
        ├── css/
        │   ├── style.css              ← design system
        │   └── leaflet.css / images/
        ├── i18n/
        │   ├── fr.json
        │   └── en.json
        └── data/
            └── sample-data.json      ← jeu de données pour le mode démonstration
```

## 15. `terraform/`

Provisionne l'intégralité de l'infrastructure Azure nécessaire, en **deux modules indépendants** :

- **`modules/network/`** : Réseau virtuel (`vnet-wireguard-lab`), sous-réseau dédié, groupe de sécurité réseau (`nsg-wireguard-lab`) avec quatre règles explicites : `AllowSSH-Admin`, `AllowWireGuard`, `AllowDashboard-Admin`, et une règle **`DenyAllOtherInbound`** en toute fin de chaîne (défense en profondeur : rien n'est autorisé par défaut).
- **`modules/compute/`** : Machine virtuelle (taille par défaut `Standard_B2s`), IP publique, disque, et injection d'un script `cloud-init.yaml.tpl` pour une préparation reproductible dès le premier démarrage.

Le fichier `terraform.tfvars.example` documente toutes les variables surchargeables (région, taille de VM, ports, IP autorisées, nom d'utilisateur admin...). Le script `deploy.ps1` encapsule le cycle `terraform init/plan/apply` pour les utilisateurs Windows/PowerShell.

## 16. `scripts/`

Scripts bash idempotents, numérotés dans l'ordre d'exécution recommandé, à lancer **sur la VM** (en root ou via `sudo`) :

| Script | Rôle |
|---|---|
| `01-install-wireguard-server.sh` | Installe WireGuard, génère les clés serveur, crée `wg0.conf`, active le service |
| `02-add-client.sh` | Ajoute un client en ligne de commande (usage direct, hors dashboard) |
| `03-install-dashboard.sh` | Installe le dashboard complet : venv Python, dépendances, service systemd, règles `sudo`, Caddy, permissions (setgid inclus) |
| `04-logging-monitoring.sh` | Met en place la capture d'état périodique (cron 5 min), la purge nocturne, les sauvegardes planifiées, et `logrotate` |
| `05-revoke-client.sh` | Révoque un client en ligne de commande |
| `06-manage-client.sh` | Fine couche CLI au-dessus de `wgctl.py`, pour l'administration avancée sans passer par le dashboard |
| `07-check-expirations.sh` | Désactive automatiquement les clients expirés (conçu pour cron nocturne) |
| `09-check-alerts.sh` | Évalue les règles d'alerte (conçu pour cron toutes les 5 minutes) |

## 17. `dashboard/backend/`

| Fichier | Responsabilité |
|---|---|
| **`app.py`** | Point d'entrée Flask. Définit les 73 routes API, la logique d'authentification (`check_auth`, `enforce_auth`), le contrôle d'accès par rôle, le flux SSE, le journal d'audit, et orchestre tous les autres modules. |
| **`auth.py`** | Modèle de comptes multi-utilisateurs : hiérarchie des rôles (`reader` / `operator` / `admin`), création/vérification de sessions, résolution des tokens API, migration du compte historique unique vers le nouveau modèle. |
| **`wgctl.py`** | Exécuté en root via `sudo -n`. Toute la logique de cycle de vie d'un client WireGuard : génération de clés, allocation d'IP, activation/désactivation, renommage, révocation, régénération, expiration, limitation de bande passante, champs de contact et RGPD, génération de QR code. |
| **`wgops.py`** | Exécuté en root via `sudo -n`. Opérations système : sauvegardes (création, liste, intégrité SHA-256, restauration sécurisée), rotation des clés serveur, redémarrage du tunnel, export global, diagnostic système. |
| **`wgstate.py`** | Lecture seule de l'état WireGuard (`wg show`), calcul des statuts (en ligne/inactif/jamais connecté), requêtage paginé du journal de connexions. |
| **`store.py`** | Couche d'accès SQLite unique pour tout le projet : schéma, migrations idempotentes, requêtes pour métriques, logs, alertes, comptes, sessions, tokens API, abonnements Web Push, dernière IP connue par client. |
| **`alerts.py`** | Moteur de règles d'alerte : catalogue de règles (inactivité, bande passante, service down, connexion/déconnexion, hors-horaires, tentatives échouées, expiration proche, nouvelle IP, seuils CPU/disque), déduplication, limitation de débit, envoi multi-canal. |
| **`reports.py`** | Génération de rapports PDF, synthèse hebdomadaire, envoi par e-mail (réutilise la configuration SMTP des alertes). |
| **`webpush.py`** | Gestion des clés VAPID, envoi de notifications Web Push à tous les abonnements enregistrés. |
| **`geoip.py`** | Résolution approximative de la localisation géographique des endpoints clients (pour la carte). |
| **`system_monitor.py`** | Métriques système : CPU, mémoire, disque, connexions TCP actives, latence réseau, température CPU (si disponible), état des services. |
| **`anomalies.py`** | Détection simple d'anomalies de débit. |
| **`settings_store.py` / `servers_store.py`** | Persistance des réglages du dashboard et du registre multi-serveurs. |

## 18. `dashboard/frontend/`

Application web monopage (SPA) **sans framework**, organisée en sections `<section class="view">` togglées par une fonction `switchView()` unique :

| Fichier | Contenu |
|---|---|
| `index.html` | Squelette complet : sidebar de navigation, topbar, l'ensemble des sections/vues, toutes les modales |
| `js/app.js` | Toute la logique applicative : appels API, rendu des tableaux, gestion d'état, i18n, thème, raccourcis clavier, Web Push, graphiques |
| `js/config.js` | Configuration runtime (URL de l'API si différente de l'origine, etc.) |
| `js/vendor/` | Bibliothèques tierces vendorisées : `chart.umd.js`, `chartjs-plugin-zoom.min.js`, `leaflet.js` |
| `css/style.css` | Design system complet (tokens de couleur, thème clair/sombre/auto, composants) |
| `sw.js` | Service worker (réception des notifications Web Push) |
| `i18n/fr.json`, `i18n/en.json` | Dictionnaires de traduction |
| `data/sample-data.json` | Jeu de données utilisé en **mode démonstration** (sans connexion API réelle) |

## 19. `dashboard/backend/tests/`

Suite de tests **pytest** (606 lignes, exécutée via le client de test Flask, sans dépendance à une VM réelle : VM WireGuard simulée par fixtures) :

| Fichier | Couverture |
|---|---|
| `conftest.py` | Fixtures partagées : environnement isolé (répertoires temporaires), rechargement des modules entre tests |
| `test_app.py` | Endpoints Flask (santé, version, clients...) |
| `test_auth.py` | Authentification multi-utilisateurs : connexion, rôles, retro-compatibilité du jeton historique, protection du dernier compte admin, scopes des tokens API |
| `test_alerts.py` | Moteur de règles d'alerte |
| `test_store.py` | Couche SQLite |
| `test_wgstate.py` | Lecture d'état WireGuard et pagination du journal |

Exécution :
```bash
cd dashboard/backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
DASHBOARD_TOKEN=test ALLOW_NO_AUTH=true python3 -m pytest tests/ -v
```

---

# Partie V : Déploiement

## 20. Prérequis

| Élément | Détail |
|---|---|
| Abonnement Azure | Actif, droits de création de groupe de ressources |
| Terraform | CLI >= 1.5 ([téléchargement](https://developer.hashicorp.com/terraform/install)) |
| Azure CLI | `az` installée et authentifiée (`az login`) : utilisée par le provider `azurerm` |
| Client SSH | OpenSSH (intégré à Windows 10/11, macOS, Linux) |
| Application WireGuard | [wireguard.com/install](https://www.wireguard.com/install/) sur chaque poste client |
| Connaissances requises | Ligne de commande Linux, notions réseau de base (NAT, CIDR, ports) |

```bash
az login
az account show
```

> **Déploiement automatisé :** depuis l'ajout de `null_resource.deploy` dans `terraform/main.tf`, `terraform apply` provisionne l'infrastructure **et** exécute automatiquement les étapes 2, 4 et 5 ci-dessous (clonage du dépôt, installation WireGuard, installation du dashboard, journalisation/monitoring) via une connexion SSH à la VM fraîchement créée. Le mot de passe administrateur du dashboard est généré par Terraform (`random_password`) et exposé en sortie (`terraform output -raw dashboard_password`). Pour revenir à un déploiement manuel, entièrement détaillé étape par étape ci-dessous, positionnez `auto_deploy = false` dans `terraform.tfvars`.

## 21. Étape 1 : Provisionner l'infrastructure Azure

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
# éditer terraform.tfvars : région, taille de VM, IP autorisées, nom d'utilisateur admin...
terraform init
terraform plan
terraform apply
```

Sous Windows/PowerShell, `deploy.ps1` encapsule ce cycle (`terraform init` → `plan` → confirmation → `apply`) ; `deploy.sh` fait de même sous Linux/macOS. À l'issue, si `auto_deploy = true` (valeur par défaut), le dashboard est déjà installé et opérationnel : le script affiche directement le lien d'accès (`dashboard_url`), l'identifiant (`dashboard_username`) et le mot de passe (`dashboard_password`) générés. Les étapes 2 à 5 ci-dessous décrivent ce que Terraform vient d'exécuter à distance ; elles ne sont nécessaires manuellement que si `auto_deploy = false`.

## 22. Étape 2 : Installer le serveur WireGuard

```bash
ssh wgadmin@<IP_PUBLIQUE>
git clone https://github.com/dspitech/blockhash-wireguard-lab.git
cd blockhash-wireguard-lab/scripts && chmod +x *.sh
sudo ./01-install-wireguard-server.sh
```

Ce script installe le paquet `wireguard`, génère la paire de clés du serveur, crée `/etc/wireguard/wg0.conf`, configure le forwarding IP et active `wg-quick@wg0` au démarrage.

## 23. Étape 3 : Créer et distribuer des clients

```bash
sudo ./02-add-client.sh alice-laptop
```

Le script génère la paire de clés du client, alloue une adresse IP dans le sous-réseau du tunnel, et affiche/enregistre le fichier `.conf` prêt à être importé dans l'application WireGuard officielle (ou scanné via QR code une fois le dashboard installé : voir Partie VII).

## 24. Étape 4 : Installer le dashboard BLOCKHash

```bash
# Depuis la racine du dépôt cloné à l'étape 2 (le script attend un dossier
# ./dashboard voisin — ne pas l'exécuter depuis scripts/) :
cd ~/blockhash-wireguard-lab
sudo ./scripts/03-install-dashboard.sh 8080
```

Ce script réalise, dans l'ordre :
1. Création du répertoire applicatif (`/opt/blockhash-dashboard`), de l'environnement virtuel Python et installation des dépendances (`requirements.txt`).
2. Génération d'un jeton d'authentification (`DASHBOARD_TOKEN`), d'un nom d'utilisateur et d'un mot de passe administrateur, écrits dans `/etc/blockhash/dashboard.env` (personnalisables via les variables d'environnement `DASHBOARD_USERNAME`/`DASHBOARD_PASSWORD`).
3. Création du service systemd `blockhash-dashboard` (Gunicorn, 2 workers `gevent`).
4. Mise en place d'une règle `sudo -n` étroitement scoped pour que `www-data` puisse invoquer `wgctl.py`/`wgops.py` sans mot de passe interactif ni accès shell.
5. Configuration de Caddy comme reverse proxy HTTPS (TLS interne auto-signé), avec un bloc dédié au flux SSE (`flush_interval -1`, pas de compression).
6. Application des permissions sur `/var/log/wireguard` : propriétaire/groupe `www-data`, **bit setgid** (voir §8 et §57).

À l'issue, l'identifiant et le mot de passe administrateur générés sont affichés **une seule fois** dans le terminal : à noter immédiatement dans un gestionnaire de secrets.

## 25. Étape 5 : Journalisation, monitoring et tâches planifiées

```bash
sudo ./04-logging-monitoring.sh
```

Met en place :
- La capture d'état WireGuard toutes les 5 minutes (insertion dans SQLite) ;
- La purge nocturne des données au-delà de la rétention configurée ;
- Les sauvegardes planifiées (désactivées par défaut, activables depuis le dashboard) ;
- La rotation des journaux via `logrotate`.

Optionnellement :
```bash
# Désactivation automatique des clients expirés (cron nocturne recommandé)
sudo crontab -e
# 0 3 * * * root /opt/blockhash-dashboard/../scripts/07-check-expirations.sh >> /var/log/wireguard/expirations.log 2>&1

# Évaluation des règles d'alerte (cron toutes les 5 minutes recommandé)
# */5 * * * * root /opt/blockhash-dashboard/../scripts/09-check-alerts.sh >> /var/log/wireguard/alerts.log 2>&1
```

## 26. Étape 6 : Valider le déploiement

```bash
# État du service
sudo systemctl status blockhash-dashboard wg-quick@wg0 caddy

# Test de connectivité locale de l'API
curl -sk https://127.0.0.1/healthz

# Test du tunnel depuis un poste client (après import de la config .conf)
wg show
ping <adresse_IP_du_serveur_dans_le_tunnel>
```

Puis ouvrir `https://<IP_PUBLIQUE>/` dans un navigateur, se connecter avec les identifiants générés à l'étape 4, et suivre l'assistant de premier lancement.

---

# Partie VI : Configuration de référence

## 27. Variables d'environnement

Fichier `/etc/blockhash/dashboard.env`, chargé par le service systemd :

| Variable | Rôle | Valeur par défaut |
|---|---|---|
| `DASHBOARD_TOKEN` | Jeton d'authentification historique (rétro-compatibilité, voir Partie VIII) | généré à l'installation |
| `DASHBOARD_USERNAME` / `DASHBOARD_PASSWORD_HASH` | Compte administrateur initial, migré automatiquement vers le nouveau modèle multi-utilisateurs au premier démarrage | générés à l'installation |
| `DASHBOARD_SESSION_TTL_SECONDS` | Durée de validité d'une session utilisateur | 2 592 000 (30 jours) |
| `ALLOW_NO_AUTH` | Désactive l'authentification (usage labo/démo isolé **uniquement**) | `false` |
| `AUTH_MAX_ATTEMPTS` / `AUTH_LOCKOUT_SECONDS` | Anti force-brute sur le login | `8` / `300` |
| `WG_INTERFACE`, `WG_DIR`, `WG_CONF_PATH` | Localisation de l'interface et de la configuration WireGuard | `wg0`, `/etc/wireguard`, `/etc/wireguard/wg0.conf` |
| `WG_SERVER_SUBNET`, `WG_PORT`, `WG_CLIENT_DNS` | Paramètres réseau du tunnel | selon script d'installation |
| `WG_CONF_GROUP` | Groupe Unix propriétaire de `wg0.conf` | `www-data` |
| `WG_LOG_CSV` | Journal CSV historique des tunnels | `/var/log/wireguard/tunnels.csv` |
| `WG_EXPORT_DIR` | Répertoire temporaire des exports (zip) | `/tmp/blockhash-exports` |
| `WG_MAX_BACKUPS` | Nombre maximal de sauvegardes conservées | `50` |
| `CLIENT_MANAGEMENT_ENABLED` / `SYSTEM_OPS_ENABLED` | Active/désactive respectivement la gestion des clients et les opérations système (`wgctl.py`/`wgops.py`) | `true` |
| `METRICS_DB_PATH` / `METRICS_DB_GROUP` | Emplacement et groupe de la base SQLite | `/var/log/wireguard/blockhash.db` / `www-data` |
| `METRICS_RETENTION_DAYS` | Rétention par défaut avant purge (surchargeable depuis Réglages) | `35` |
| `AUDIT_LOG_PATH` | Journal d'audit append-only | `/var/log/wireguard/audit.log` |
| `SETTINGS_PATH`, `ALERTS_CONFIG_PATH`, `REPORTS_CONFIG_PATH`, `SERVERS_CONFIG_PATH` | Fichiers JSON de configuration persistée | voir §28 |
| `BLOCKHASH_CONFIG_DIR` | Répertoire des clés VAPID (Web Push) | `/etc/blockhash` |
| `VAPID_CONTACT_EMAIL` | Adresse de contact incluse dans les revendications VAPID | `mailto:admin@example.com` |
| `GEOIP_TTL_SEC` | Durée de mise en cache des résolutions GeoIP | selon `geoip.py` |
| `FRONTEND_DIR`, `PORT` | Chemin du frontend statique et port d'écoute de Gunicorn | `$APP_DIR/frontend`, `8080` |

## 28. Fichiers de configuration persistés

| Fichier | Contenu |
|---|---|
| `/etc/blockhash/dashboard-settings.json` | Réglages généraux : seuil « en ligne », rétention, format de date, fuseau horaire, langue, notifications desktop, planning de sauvegardes, politiques de conformité |
| `/etc/blockhash/alerts-config.json` | Configuration complète du moteur d'alertes : règles activées, cooldowns, canaux (SMTP, Slack, Discord, Telegram, Web Push) |
| `/etc/blockhash/reports-config.json` | Configuration du rapport hebdomadaire (activation, destinataire) |
| `/etc/blockhash/servers.json` | Registre multi-serveurs (le cas échéant) |
| `/etc/blockhash/vapid_private_key.pem` | Clé privée VAPID (Web Push), générée automatiquement au premier envoi, permissions `0600` |

## 29. Service systemd

`/etc/systemd/system/blockhash-dashboard.service` (généré par le script d'installation) :

```ini
[Service]
User=www-data
WorkingDirectory=/opt/blockhash-dashboard/backend
EnvironmentFile=/etc/blockhash/dashboard.env
ExecStart=/opt/blockhash-dashboard/venv/bin/gunicorn \
    -w 2 --worker-class gevent --worker-connections 1000 \
    --timeout 120 -b 127.0.0.1:8080 app:app
Restart=on-failure
```

Le worker `gevent` (plutôt que le worker synchrone par défaut ou `gthread`) est **indispensable** : le flux SSE maintient une connexion HTTP ouverte en continu par onglet client ; un worker à base de threads OS saturerait rapidement son pool dès quelques onglets ouverts simultanément (voir Partie XI pour le détail de cet incident et de sa correction).

## 30. Reverse proxy Caddy

Extrait représentatif de `/etc/caddy/Caddyfile` :

```caddyfile
https://<IP_ou_domaine> {
    bind 0.0.0.0
    tls internal

    @sse path /api/events/stream
    handle @sse {
        reverse_proxy 127.0.0.1:8080 {
            flush_interval -1
        }
    }
    handle {
        encode gzip
        reverse_proxy 127.0.0.1:8080
    }
}
```

Le flux SSE est **explicitement exclu** de la compression `gzip` (qui nécessite de bufferiser le contenu : incompatible avec un flux qui ne se termine jamais) et bénéficie d'un `flush_interval -1` pour un envoi immédiat de chaque évènement, sans latence de bufferisation côté proxy.

## 31. Tâches planifiées (cron)

| Fréquence | Commande | Rôle |
|---|---|---|
| Toutes les 5 min | Script de capture (`04-logging-monitoring.sh`) | Insère un échantillon de débit par client dans SQLite |
| Toutes les 5 min | `09-check-alerts.sh` | Évalue les règles d'alerte (inactivité, bande passante, service, expiration, seuils système, nouvelle IP) |
| Nuit (3h30) | `store.py prune` | Purge les données (logs, échantillons, alertes) au-delà de la rétention configurée |
| Nuit (4h) | `wgops.py auto-backup` | Sauvegarde planifiée, auto-limitée selon le planning configuré dans Réglages (désactivé/quotidien/hebdomadaire/mensuel) |
| Nuit | `07-check-expirations.sh` | Désactive automatiquement les clients dont la date d'expiration est dépassée |

---

# Partie VII : Fonctionnalités

BLOCKHash est organisé en **onze sections** accessibles depuis la barre de navigation latérale. Cette partie documente chaque fonctionnalité de façon exhaustive.

## 32. Vue d'ensemble (dashboard)

- Compteurs en temps réel : clients configurés, en ligne, inactifs, désactivés.
- Répartition des statuts (graphique).
- Débit du tunnel (graphique temps réel).
- Clients connectés, avec durée de connexion.
- Expirations à venir.
- Activité récente (flux d'événements).
- Actions rapides (accès direct aux tâches courantes).

## 33. Gestion des clients

**Cycle de vie complet**
- Création unitaire, avec champs de contact (prénom, e-mail, téléphone, adresse, fonction, tags, notes) et consentement RGPD horodaté.
- Renommage, activation/désactivation, révocation, régénération des clés.
- Limitation de bande passante (montante/descendante, en Mbit/s).
- Date d'expiration avec désactivation automatique (cron nocturne) et alerte de rappel configurable (J-N).

**Création en masse**
- Ajout multiple par collage d'une liste (`nom,email,téléphone`).
- Import CSV avec modèle téléchargeable, aperçu en mode **dry-run** avant exécution, rapport d'erreurs ligne par ligne.

**Distribution de configuration**
- Téléchargement du fichier `.conf`.
- QR code d'appairage (affichage, téléchargement PNG, copie du texte de configuration).

**Filtres et recherche**
- Chips de statut (Tous / En ligne / Inactifs / Désactivés) avec compteurs temps réel.
- Filtres avancés : date de création, date d'expiration, présence d'e-mail/téléphone.
- Recherche multi-critères (nom, e-mail, IP, endpoint), filtres sauvegardés en local.
- Tri par colonne, pagination configurable (10/25/50/100 par page).

**Actions groupées**
- Sélection multiple, activation/désactivation/révocation/export en masse.

**Détail et historique**
- Fiche détaillée par client : dernier handshake, nombre de reconnexions (24 h), dernier endpoint, sessions récentes.
- Export RGPD complet (profil + historique de connexion) au format JSON.

**Export**
- Export CSV de la liste filtrée.

## 34. Journal des connexions

- Historique paginé au niveau base de données (aucune limite de volume affichable).
- Recherche texte (client, IP, endpoint), filtre par statut.
- Filtres avancés : plage de dates, volume minimal/maximal.
- Recherches sauvegardées (rappel rapide d'une combinaison de filtres).
- Détail d'une session en un clic (endpoint complet, volumes, clé publique).
- **Heatmap des connexions** (créneaux horaires × jours de la semaine, 30 derniers jours).
- Export CSV de la page courante.

## 35. Monitoring

- Graphique de débit long terme, avec **zoom molette et pan par glisser**.
- Métriques hôte : CPU, mémoire, disque, connexions TCP actives, latence réseau (à la demande), température CPU (si le matériel l'expose).
- Carte de géolocalisation des endpoints (GeoIP approximatif), avec **top 10 des pays** représentés.
- Détection d'anomalies de débit.
- État des services surveillés (`wg-quick@wg0`, `blockhash-dashboard`).

## 36. Alertes

**Catalogue de règles**
- Connexion / déconnexion d'un client (temps réel).
- Client inactif depuis N jours (ou jamais connecté).
- Dépassement d'un seuil de bande passante.
- Service hors ligne.
- Connexion hors plage horaire autorisée.
- Tentatives d'authentification échouées répétées.
- Expiration de client imminente.
- Connexion depuis une IP jamais vue pour ce client.
- Seuils système : charge CPU, occupation disque.

**Canaux de notification**
- E-mail (SMTP configurable), Slack, Discord, Telegram : chacun activable/désactivable individuellement.
- **Web Push** (notification navigateur, y compris onglet fermé, via service worker + clés VAPID), réservée par défaut aux alertes critiques.
- Bouton de test par canal.

**Gouvernance des alertes**
- Activation globale, cooldown par règle (anti-répétition), plafond global d'alertes par heure (anti-tempête de notifications).
- Historique complet : filtres par sévérité/client/règle/dates, marquage lu/archivé, suppression, export CSV.
- Tableau de bord : volume par jour, top clients alertés, délai moyen avant lecture (MTTA).
- Vue des règles actuellement en cooldown (« déduplication active »).

## 37. Conformité

- Détection des clients inactifs au-delà d'un seuil, avec **politiques par tag** (ex. `#vip` : 180 jours, `#externe` : 30 jours) et liste d'exceptions documentées.
- Export d'un rapport PDF de conformité.
- Rapport hebdomadaire automatique par e-mail (activable, configurable).

## 38. Système

- **Sauvegardes** : création manuelle avec description libre, planification (désactivé/quotidien/hebdomadaire/mensuel, auto-limitée sans droit d'écriture sur la crontab pour `www-data`), intégrité vérifiée par empreinte **SHA-256**, téléchargement protégé par re-saisie du mot de passe (avec anti force-brute dédié), **restauration à double confirmation** (mot de passe + saisie du mot « RESTORE »), sauvegarde de sécurité automatique de l'état courant avant toute restauration.
- **Diagnostic** : état du service `wg-quick`, interface WireGuard active, connectivité réseau sortante, espace disque, permissions des fichiers critiques : rapport consultable depuis l'interface.
- **Journal d'audit** : aperçu des 5 dernières actions sur la page Système, page dédiée avec filtres complets (action, IP, plage de dates) et export.
- **Opérations** : redémarrage du tunnel et rotation des clés serveur, avec aperçu du nombre de clients impactés avant confirmation, et entrée systématique au journal d'audit.
- **Export global** : archive ZIP de l'ensemble des configurations clients.

## 39. Réglages

- Seuil de détection « en ligne », rétention des données (avec purge manuelle immédiate en plus de la purge automatique nocturne).
- Notifications desktop (Notification API) et **Web Push** (abonnement/désabonnement, test).
- Format de date, fuseau horaire, langue (FR/EN).
- Politiques de conformité par tag (voir §37).
- Thème clair / sombre / automatique (suit les préférences système, mise à jour en direct).

## 40. Utilisateurs et rôles

- Comptes nominatifs avec trois rôles : **lecteur** (consultation), **opérateur** (+ gestion des clients), **admin** (accès complet, y compris opérations système et gouvernance des comptes).
- CRUD complet : création, modification (rôle, statut actif/inactif, réinitialisation de mot de passe), suppression.
- Garde-fou intégré : impossible de supprimer ou de rétrograder le **dernier compte admin actif**.
- Page dédiée, réservée aux comptes admin.

## 41. Tokens API

- Génération de tokens nommés, avec **scope** (lecture / écriture / admin) et expiration optionnelle.
- Le token en clair n'est affiché **qu'une seule fois** à la création (seule son empreinte est stockée en base).
- Liste des tokens actifs (créateur, dernière utilisation, expiration), révocation immédiate.
- Page dédiée, réservée aux comptes admin.

## 42. Aide intégrée

- Page dédiée avec sept fiches procédurales pas-à-pas : créer un client, importer en masse, télécharger une configuration, consulter les logs, créer une alerte, restaurer une sauvegarde, gérer les utilisateurs.

## 43. Fonctionnalités transverses

- **Temps réel** : mise à jour de l'ensemble du dashboard via Server-Sent Events, sans rafraîchissement de page.
- **Internationalisation** : interface statique disponible en français et anglais.
- **Thème** : clair / sombre / automatique.
- **Recherche globale** et **raccourcis clavier** (`g c` / `g a` / `g m` pour naviguer, `/` pour rechercher, `?` pour l'aide, `Échap` pour fermer une fenêtre modale).
- **Mode démonstration** : le dashboard peut être exploré sans connexion API réelle, à partir d'un jeu de données d'exemple.
- **Responsive** : utilisable sur mobile et tablette.
- **Assistant de premier lancement** : vérifications de bon fonctionnement à la première connexion.
- **Signalement** : bouton d'envoi de retour/bug pré-rempli avec le contexte technique.

## 44. Provisioning VPN depuis un annuaire

Génère des clients VPN à partir d'un annuaire d'entreprise existant, pour éviter la double saisie manuelle. Nouvel onglet **Provisioning**, réservé au rôle `admin`.

**Livré (Phase 1)** :
- Connecteur **LDAP générique** (`dashboard/backend/directory/ldap_connector.py`), couvrant Active Directory local, Azure AD Domain Services, OpenLDAP, Samba AD, FreeIPA, JumpCloud LDAP et Google Secure LDAP — LDAPS/StartTLS obligatoire, échappement systématique des valeurs dans les filtres LDAP (protection anti-injection), détection du bit `ACCOUNTDISABLE` pour les comptes désactivés côté AD.
- Interface abstraite `DirectoryConnector` (`directory/base.py`) : tout le reste du module ignore le type de source réel, ce qui permettra d'ajouter Microsoft Graph ou Google Workspace sans réécrire l'explorateur ni le moteur de provisioning.
- Gestion des sources (créer / tester / activer-désactiver / supprimer), avec le mot de passe de bind LDAP **toujours** résolu depuis une variable d'environnement (jamais stocké dans `directory_sources.config_json` ni dans la base SQLite).
- Explorateur : recherche paginée, sélection multiple, statut VPN affiché par utilisateur.
- **Dry-run obligatoire** avant toute exécution : détecte les comptes déjà provisionnés, les conflits de nom, les comptes désactivés.
- **Job asynchrone** (thread dédié) avec suivi de progression par polling, journalisé dans `provisioning_log` et dans `audit.log`. Réutilise `wgctl.py` via `run_wgctl` — aucune réimplémentation de la création de client.

**Feuille de route (non livré)** :
- Connecteurs API REST **Microsoft Graph** (M365/Entra ID) et **Google Admin SDK** (Google Workspace) — l'architecture (`DirectoryConnector`) est prête à les recevoir.
- Politiques de provisioning par groupe, quotas par source, tags dynamiques calculés depuis les attributs annuaire.
- Synchronisation périodique (cron) avec désactivation automatique des comptes annuaire désactivés, historique des synchronisations avec diff.
- Rollback d'un job, notifications post-provisioning (réutilisation d'`alerts.py`), export PDF signé du rapport.
- Détection des comptes orphelins et réconciliation manuelle (association rétroactive client VPN ↔ utilisateur annuaire).
- Passage du suivi de job du polling au flux SSE déjà utilisé par le reste du dashboard (voir §43, temps réel).
- Tests d'intégration contre un Samba AD / OpenLDAP de laboratoire (les tests actuels couvrent la logique en unitaire, avec un serveur LDAP simulé en mémoire).

---

# Partie VIII : Sécurité

## 45. Modèle d'authentification

BLOCKHash distingue trois mécanismes d'authentification, tous vérifiés par une fonction centrale (`check_auth()` dans `app.py`) :

1. **Comptes utilisateurs nominatifs** : `/api/login` échange un couple identifiant/mot de passe contre un **jeton de session** propre à l'utilisateur (aléatoire, haché en SQLite, jamais stocké en clair), valable par défaut 30 jours.
2. **Tokens API** : jetons nommés et scopés, créés depuis la page **Tokens API**, pour l'automatisation. Le jeton en clair n'est affiché qu'à sa création.
3. **Jeton historique partagé (`DASHBOARD_TOKEN`)** : conservé pour la rétrocompatibilité avec les déploiements antérieurs au modèle multi-utilisateurs ; traité comme un accès admin implicite. **Recommandation** : le désactiver (retirer la variable de `dashboard.env`) une fois la migration vers des comptes nominatifs terminée.

Le mot de passe est haché via `werkzeug.security` (scrypt/pbkdf2 selon version), jamais stocké en clair. Un mécanisme anti force-brute limite les tentatives de connexion par adresse IP (verrouillage temporaire configurable).

## 46. Contrôle d'accès par rôle (RBAC)

Trois rôles, avec une hiérarchie stricte :

| Rôle | Peut consulter | Peut modifier | Peut administrer |
|---|---|---|---|
| **reader** | Toutes les pages en lecture | N/A | N/A |
| **operator** | Tout ce que `reader` voit | Clients (création, édition, révocation, import), marquage des alertes | N/A |
| **admin** | Tout | Tout ce que `operator` peut faire | Réglages globaux, comptes utilisateurs, tokens API, opérations système, sauvegardes, signalements |

La vérification est appliquée à **deux niveaux**, volontairement redondants :
- **Backend** (`auth.required_role_for(method, path)`) : la seule source de vérité réelle pour la sécurité ; chaque requête API est évaluée avant exécution.
- **Frontend** : les boutons et sections réservés à un rôle supérieur sont masqués dynamiquement (attribut `data-role-min`), pour une expérience cohérente plutôt qu'un message d'erreur après un clic. Le masquage frontend est un confort d'usage, **jamais** un mécanisme de sécurité à lui seul.

## 47. Protection des données et RGPD

- Champs de contact client (nom, e-mail, téléphone, adresse, fonction) et **consentement horodaté**.
- Export complet des données d'un client (profil + historique de connexion) au format JSON, en réponse à une demande d'accès.
- Politiques de rétention et de purge automatique configurables.
- Aucune donnée transmise à un service tiers sans configuration explicite (les canaux d'alerte : e-mail, Slack, Discord, Telegram, Web Push : sont tous opt-in et configurés par l'organisation elle-même).

## 48. Traçabilité et audit

- **Journal d'audit** append-only (`/var/log/wireguard/audit.log`) : toute action de modification (création/révocation de client, connexion, échec d'authentification, rotation de clés, restauration, gestion des comptes...) y est consignée avec horodatage, IP source et détail structuré.
- Consultable depuis l'interface (aperçu + page dédiée avec filtres), exportable.
- **Signalements de bugs** eux-mêmes tracés (auteur, catégorie, sévérité, statut de traitement).

## 49. Checklist de durcissement

- [ ] Restreindre les règles NSG `AllowSSH-Admin` et `AllowDashboard-Admin` à des plages d'IP connues plutôt qu'à `Internet`.
- [ ] Désactiver `DASHBOARD_TOKEN` une fois tous les comptes/tokens nominatifs en place.
- [ ] Remplacer le certificat TLS interne auto-signé de Caddy par un certificat émis par une autorité reconnue (interne à l'organisation ou publique) si le dashboard est exposé au-delà d'un cercle restreint.
- [ ] Activer les alertes `failed_auth_attempts` et `off_hours`.
- [ ] Configurer un canal de notification (e-mail a minima) pour être alerté en cas d'événement critique.
- [ ] Vérifier régulièrement le journal d'audit et la boîte de réception des signalements.
- [ ] Maintenir à jour le système d'exploitation, le noyau (module WireGuard), et les dépendances Python (`requirements.txt`).
- [ ] Sauvegarder `wg0.conf` et la base SQLite en dehors de la VM (voir Partie X).

---

# Partie IX : Référence API

## 50. Authentification des appels API

Toutes les routes sous `/api/*` (à l'exception de `/api/login`) exigent un en-tête :

```
X-API-Token: <jeton_de_session_ou_token_API>
```

```bash
# Connexion
curl -sk -X POST https://<host>/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"••••••••"}'
# -> {"token": "sess_...", "username": "alice", "role": "operator"}

# Appel authentifié
curl -sk https://<host>/api/clients -H "X-API-Token: sess_..."
```

## 51. Catalogue des endpoints

73 routes, regroupées par domaine fonctionnel :

| Domaine | Exemples de routes | Rôle minimal |
|---|---|---|
| Authentification | `POST /api/login`, `GET /api/auth/me` | public / reader |
| Clients | `GET/POST /api/clients`, `PATCH/DELETE /api/clients/<nom>`, `/bulk`, `/export`, `/<nom>/config`, `/<nom>/history`, `/<nom>/gdpr-export` | reader (lecture) / operator (écriture) |
| Journal | `GET /api/logs`, `/api/logs/heatmap` | reader |
| Monitoring | `GET /api/system`, `/api/geoip`, `/api/anomalies` | reader |
| Alertes | `GET/PATCH /api/alerts/config`, `/api/alerts/history`, `/api/alerts/test`, `/api/alerts/dedup` | reader (lecture) / admin (configuration) |
| Conformité | `GET /api/compliance`, `PATCH /api/compliance/policies` | reader (lecture) / admin (écriture) |
| Rapports | `POST /api/reports/pdf`, `/api/reports/weekly-config`, `/api/reports/weekly-send` | operator (PDF) / admin (hebdomadaire) |
| Système | `GET/POST /api/system/backups`, `/restore`, `/download`, `/api/system/diagnostics`, `/api/system/audit`, `/restart-tunnel`, `/rotate-server-keys` | admin |
| Réglages | `GET/PATCH /api/settings` | reader (lecture) / admin (écriture) |
| Utilisateurs | `GET/POST /api/users`, `PATCH/DELETE /api/users/<nom>` | admin |
| Tokens API | `GET/POST /api/tokens`, `DELETE /api/tokens/<id>` | admin |
| Web Push | `GET /api/push/vapid-public-key`, `POST /api/push/subscribe`, `/unsubscribe`, `/test` | reader / admin (test) |
| Signalements | `POST /api/bug-reports` (tout rôle), `GET/PATCH /api/bug-reports` (admin) | reader (création) / admin (traitement) |
| Flux temps réel | `GET /api/events/stream` (Server-Sent Events) | reader |

---

# Partie X : Exploitation

## 52. Sauvegardes et rétention

- **Sauvegardes de configuration** (`wg0.conf`) : création manuelle avec description, planification automatique (désactivée par défaut), intégrité vérifiée par SHA-256, conservation des `WG_MAX_BACKUPS` (50 par défaut) plus récentes.
- **Restauration** : double confirmation (mot de passe + saisie de « RESTORE »), avec sauvegarde de sécurité automatique de l'état courant avant toute écrasement.
- **Rétention des données applicatives** (logs, métriques, alertes) : purge automatique nocturne selon `METRICS_RETENTION_DAYS`, purge manuelle immédiate disponible depuis Réglages.
- **Recommandation** : répliquer périodiquement `/etc/wireguard/backups/` et `/var/log/wireguard/blockhash.db` vers un stockage hors VM (snapshot de disque Azure, ou synchronisation externe).

## 53. Mise à jour de la plateforme

```bash
# Sauvegarder avant toute mise à jour
sudo -u www-data /opt/blockhash-dashboard/venv/bin/python3 /opt/blockhash-dashboard/backend/wgops.py backup --label pre-update

# Déployer le nouveau code (dashboard/)
# ... copier les fichiers mis à jour ...

# Mettre à jour les dépendances si requirements.txt a changé
sudo -u www-data /opt/blockhash-dashboard/venv/bin/pip install -r /opt/blockhash-dashboard/backend/requirements.txt

# Redémarrer
sudo systemctl restart blockhash-dashboard
sudo systemctl status blockhash-dashboard
```

## 54. Supervision de la plateforme elle-même

- Page **Système > Diagnostic** : état du service `wg-quick`, connectivité sortante, espace disque, permissions.
- Page **Système > Journal d'audit** : détection d'activité anormale (échecs d'authentification répétés, actions hors horaires).
- `journalctl -u blockhash-dashboard -f` pour les logs applicatifs en direct.
- Alerte `service_down` (voir Partie VII, §36) pour être notifié si `wg-quick@wg0` ou `blockhash-dashboard` s'arrête.

## 55. Capacité et dimensionnement

| Facteur | Recommandation |
|---|---|
| Nombre de clients WireGuard | Quelques centaines sans ajustement particulier (le goulot est le CPU de chiffrement, pas le dashboard) |
| Connexions dashboard simultanées (onglets ouverts, flux SSE) | Le worker `gevent` gère plusieurs centaines de connexions SSE concurrentes par worker (2 workers par défaut) sans épuisement de threads |
| Taille de la VM | `Standard_B2s` convient pour un usage PME ; passer à une taille supérieure si le nombre de clients ou la fréquence des rapports/alertes est élevé |
| Base SQLite | Adaptée jusqu'à plusieurs millions de lignes avec une rétention raisonnable (35 jours par défaut) ; au-delà, envisager une purge plus agressive |

---

# Partie XI : Dépannage

## 56. Méthodologie générale

1. Vérifier l'état des services : `systemctl status blockhash-dashboard wg-quick@wg0 caddy`.
2. Consulter les logs applicatifs : `journalctl -u blockhash-dashboard -n 100 --no-pager`.
3. Tester l'API en local, en s'affranchissant du reverse proxy : `curl -sk https://127.0.0.1/healthz`.
4. Vérifier les permissions des fichiers partagés entre root et www-data (voir incident ci-dessous).
5. Utiliser la page **Système > Diagnostic** du dashboard lui-même.

## 57. Incidents courants

### `terraform apply` reste bloqué sur « null_resource.deploy: Still creating... » indéfiniment

**Symptôme.** Le déploiement automatisé (`auto_deploy = true`, voir Partie V) semble tourner indéfiniment sans jamais se terminer — alors qu'une vérification manuelle sur la VM montre que WireGuard **et** le dashboard sont bel et bien installés et fonctionnels. À l'interruption manuelle (Ctrl+C), Terraform affiche `remote command exited without exit status or exit signal`.

**Cause.** `needrestart`, un mécanisme Ubuntu qui affiche une invite interactive (`whiptail`) dès qu'une mise à jour de paquet nécessite de redémarrer un service — quasi systématique avec `package_upgrade: true` (mise à jour de `libc`/`openssl` au premier boot) et les `apt install` des scripts. Sur une session SSH non interactive (le `remote-exec` de Terraform), cette invite ne reçoit jamais de réponse : la commande sous-jacente a beau être terminée depuis longtemps, le canal SSH ne se referme jamais, et Terraform attend indéfiniment un signal de fin qui ne viendra jamais.

**Correctif appliqué dans ce dépôt.**
- `terraform/modules/compute/cloud-init.yaml.tpl` désactive le mode interactif de `needrestart` (`$nrconf{restart} = 'a';`) via `write_files`, **avant** que `package_upgrade` ne s'exécute — c'est le point critique : une désactivation plus tardive (`runcmd`) arriverait après le blocage potentiel.
- Les trois scripts (`01`, `03`, `04`) exportent en plus `DEBIAN_FRONTEND=noninteractive` et `NEEDRESTART_MODE=a` en tout début d'exécution, en défense en profondeur pour un lancement manuel hors Terraform.
- `terraform/main.tf` enveloppe chaque étape du `remote-exec` dans `timeout Nm ... </dev/null` : `</dev/null` coupe l'entrée standard (toute invite imprévue reçoit un EOF immédiat plutôt que d'attendre), et `timeout` fait échouer proprement l'étape au bout de quelques minutes si un cas imprévu bloque quand même la commande, plutôt que de bloquer `terraform apply` indéfiniment.

**Si le problème persiste malgré ce correctif** (VM déjà provisionnée avant sa mise en place, ou autre cause de blocage) : `ssh` manuellement sur la VM pendant que `terraform apply` est bloqué, et inspecter les processus en cours (`ps auxf`) pour identifier ce qui retient la session ouverte ; `sudo needrestart -r a` purge une invite `needrestart` déjà en attente.

### « attempt to write a readonly database » au login ou à toute action utilisateur/token

**Cause.** La base SQLite (`blockhash.db`) est historiquement écrite par un cron **root** (capture d'état WireGuard, purge) et lue par `www-data` (Flask) en lecture seule. Depuis l'introduction des comptes multi-utilisateurs, des tokens API et du marquage des alertes, **Flask a lui aussi besoin d'écrire** dans cette base. Or, si un processus root réécrit physiquement le fichier (ex. `VACUUM` lors de la purge), il redevient root-only en écriture pour `www-data`.

**Correctif appliqué dans ce dépôt.**
```bash
# Sur une VM déjà affectée par ce symptôme :
sudo chown www-data:www-data /var/log/wireguard/blockhash.db*
sudo chmod 0660 /var/log/wireguard/blockhash.db*
sudo chmod g+s /var/log/wireguard
```
Le script `03-install-dashboard.sh` applique désormais ce réglage (mode `0660` + bit setgid) dès l'installation, et `store.py::_fix_permissions()` le réapplique automatiquement après chaque écriture, quel que soit le processus (root ou www-data) qui l'a effectuée.

### La page Alertes affiche « The requested URL was not found on the server »

**Cause.** Une route Flask manquante (décorateur de route absent, généralement suite à une édition manuelle incomplète du code). Vérifier :
```bash
cd dashboard/backend
python3 -c "
import app
for r in app.app.url_map.iter_rules():
    if 'alerts' in str(r): print(r, r.methods)
"
```
Toutes les routes attendues (`/api/alerts/config`, `/api/alerts/history`, `/api/alerts/dedup`, `/api/alerts/test`...) doivent apparaître.

### Un bouton d'export/téléchargement ne fait rien

**Cause.** Une navigation directe (`window.open()` ou `window.location.href`) vers une route `/api/*` protégée par jeton ne transmet **pas** l'en-tête `X-API-Token` : la requête échoue en 401 silencieusement (pas de page d'erreur visible, juste rien). Le frontend utilise systématiquement un téléchargement via `fetch()` authentifié suivi de la création d'un lien `<a download>` (voir `downloadWithAuth()` dans `app.js`), jamais de navigation directe vers l'API.

### Le worker Gunicorn "avale" les connexions et le dashboard devient inaccessible

**Cause.** Utilisation du worker par défaut (synchrone) ou `gthread` avec un flux SSE ouvert en continu par onglet : le pool de threads s'épuise dès que quelques onglets restent ouverts. **Solution** : `--worker-class gevent`, seule option adaptée à un flux SSE de longue durée (voir Partie VI, §29).

### Le rapport hebdomadaire ou l'export PDF échoue sans message clair

- Vérifier que `fpdf2` est installé dans le venv : `pip show fpdf2`.
- Vérifier qu'un canal e-mail est configuré et testé (page **Alertes > Configurer les canaux**, bouton **Tester**) : le rapport hebdomadaire réutilise cette même configuration SMTP.
- Depuis cette révision, un échec d'envoi renvoie un code HTTP explicite (422) avec le motif exact, au lieu d'un succès silencieux à tort.

---

# Partie XII : Limites connues et feuille de route

## 58. Hors périmètre assumé

Ces choix sont **documentés et délibérés**, pas des oublis :

| Fonctionnalité | Statut | Raison |
|---|---|---|
| SSO / LDAP / Active Directory / OIDC | Non implémenté | Nécessiterait une intégration à un fournisseur d'identité externe, hors périmètre d'un projet auto-hébergé de cette taille |
| Authentification à deux facteurs (2FA/TOTP) | Non implémenté | Techniquement compatible avec le modèle multi-utilisateurs actuel, mais volontairement reporté pour éviter de complexifier l'authentification avant sa stabilisation |
| Internationalisation du contenu généré côté serveur | Partiel | Les messages d'alerte, le journal d'audit et les erreurs API restent en français ; seule l'interface statique est traduite (FR/EN) |
| Vraie notification Web Push à grande échelle | Implémenté en best-effort | Repose sur le protocole standard (VAPID) sans infrastructure de file d'attente dédiée ; convient à un usage d'équipe, pas à des milliers d'abonnés |
| Multi-tenant | Non implémenté | Le projet est conçu pour une organisation unique |

## 59. Feuille de route

- Authentification à deux facteurs (TOTP) pour les comptes admin.
- Intégration SSO (OIDC a minima).
- Rétention et purge automatique différenciées par type de donnée (au-delà du réglage global actuel).
- Export/import chiffré de sauvegardes pour la reprise après sinistre cross-instance.

---

# Annexes

## 60. Glossaire

| Terme | Définition |
|---|---|
| **Pair (peer)** | Toute extrémité d'un tunnel WireGuard, serveur ou client, identifiée par sa clé publique |
| **Handshake** | Poignée de main cryptographique établissant un tunnel WireGuard |
| **AllowedIPs** | Plage d'adresses IP qu'un pair est autorisé à envoyer/recevoir via le tunnel (cœur du Cryptokey Routing) |
| **Forward secrecy** | Propriété garantissant que la compromission d'une clé à long terme ne compromet pas les communications passées |
| **RBAC** | *Role-Based Access Control* : contrôle d'accès fondé sur des rôles |
| **VAPID** | *Voluntary Application Server Identification* : mécanisme d'authentification des notifications Web Push |
| **SSE** | *Server-Sent Events* : flux HTTP permettant au serveur de pousser des évènements en continu vers le navigateur |
| **NSG** | *Network Security Group* : groupe de règles de pare-feu au niveau réseau Azure |

## 61. Aide-mémoire des commandes

```bash
# État général
sudo systemctl status blockhash-dashboard wg-quick@wg0 caddy
sudo wg show

# Logs
sudo journalctl -u blockhash-dashboard -f
sudo tail -f /var/log/wireguard/audit.log

# Gestion manuelle d'un client (hors dashboard)
sudo /opt/blockhash-dashboard/venv/bin/python3 /opt/blockhash-dashboard/backend/wgctl.py add --name alice
sudo /opt/blockhash-dashboard/venv/bin/python3 /opt/blockhash-dashboard/backend/wgctl.py revoke --name alice

# Sauvegarde/restauration manuelle
sudo /opt/blockhash-dashboard/venv/bin/python3 /opt/blockhash-dashboard/backend/wgops.py backup --label manuel
sudo /opt/blockhash-dashboard/venv/bin/python3 /opt/blockhash-dashboard/backend/wgops.py list-backups

# Tests backend
cd dashboard/backend && DASHBOARD_TOKEN=test ALLOW_NO_AUTH=true python3 -m pytest tests/ -v
```

## 62. Licence

Ce projet est distribué sous licence **MIT**. Voir le fichier [`LICENSE`](./LICENSE) pour le texte complet.

---

<div align="center">

*Documentation maintenue au fil des évolutions du projet : dernière refonte complète incluant l'authentification multi-utilisateurs, les tokens API scopés, le moteur d'alertes étendu, les notifications Web Push, l'internationalisation et le centre de signalement.*

</div>
