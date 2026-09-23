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

Ce README est la documentation de référence complète du projet **BLOCKHash**. Il s'adresse aussi bien à un·e ingénieur·e réseau qui découvre WireGuard qu'à une équipe plateforme qui évalue l'intégration du projet dans son système d'information. Il couvre, sans rien omettre :

- Les fondamentaux de WireGuard (le protocole VPN sur lequel tout repose) ;
- L'architecture complète du système, composant par composant ;
- Le détail de chaque dossier et fichier du dépôt ;
- La stack technique utilisée, et pourquoi ;
- L'intégralité des fonctionnalités de la plateforme ;
- Le déploiement pas à pas, de zéro à un environnement opérationnel ;
- Le modèle de sécurité et le guide de durcissement ;
- L'exploitation courante (sauvegardes, mises à jour, supervision) ;
- Le dépannage des incidents les plus courants.

---

## Sommaire

**Partie I : Comprendre WireGuard**
1. [Qu'est-ce que WireGuard](#1-quest-ce-que-wireguard)
2. [Pourquoi WireGuard : comparaison avec IPsec et OpenVPN](#2-pourquoi-wireguard--comparaison-avec-ipsec-et-openvpn)
3. [Fondations cryptographiques](#3-fondations-cryptographiques)
4. [Fonctionnement technique : Cryptokey Routing](#4-fonctionnement-technique--cryptokey-routing)
5. [Avantages et limites](#5-avantages-et-limites)
6. [Cas d'usage type en entreprise](#6-cas-dusage-type-en-entreprise)

**Partie II : Qu'est-ce que BLOCKHash**
7. [Présentation générale](#7-présentation-générale)
8. [Proposition de valeur](#8-proposition-de-valeur)
9. [Ce que BLOCKHash n'est pas](#9-ce-que-blockhash-nest-pas)

**Partie III : Architecture**
10. [Vue d'ensemble de l'architecture](#10-vue-densemble-de-larchitecture)
11. [Composants du système](#11-composants-du-système)
12. [Flux réseau et ports](#12-flux-réseau-et-ports)
13. [Cycle de vie d'une connexion client](#13-cycle-de-vie-dune-connexion-client)
14. [Modèle de séparation des privilèges](#14-modèle-de-séparation-des-privilèges)

**Partie IV : Stack technique**
15. [Infrastructure](#15-infrastructure)
16. [Système et réseau](#16-système-et-réseau)
17. [Backend](#17-backend)
18. [Frontend](#18-frontend)
19. [Dépendances complètes](#19-dépendances-complètes)

**Partie V : Structure du projet**
20. [Vue d'ensemble de l'arborescence](#20-vue-densemble-de-larborescence)
21. [`terraform/`](#21-terraform)
22. [`scripts/`](#22-scripts)
23. [`dashboard/backend/`](#23-dashboardbackend)
24. [`dashboard/frontend/`](#24-dashboardfrontend)
25. [`dashboard/backend/tests/`](#25-dashboardbackendtests)

**Partie VI : Déploiement**
26. [Prérequis](#26-prérequis)
27. [Étape 1 : Provisionner l'infrastructure Azure](#27-étape-1--provisionner-linfrastructure-azure)
28. [Étape 2 : Installer le serveur WireGuard](#28-étape-2--installer-le-serveur-wireguard)
29. [Étape 3 : Créer et distribuer des clients](#29-étape-3--créer-et-distribuer-des-clients)
30. [Étape 4 : Installer le dashboard BLOCKHash](#30-étape-4--installer-le-dashboard-blockhash)
31. [Étape 5 : Journalisation, monitoring et tâches planifiées](#31-étape-5--journalisation-monitoring-et-tâches-planifiées)
32. [Étape 6 : Valider le déploiement](#32-étape-6--valider-le-déploiement)

**Partie VII : Configuration de référence**
33. [Variables d'environnement](#33-variables-denvironnement)
34. [Fichiers de configuration persistés](#34-fichiers-de-configuration-persistés)
35. [Service systemd](#35-service-systemd)
36. [Reverse proxy Caddy](#36-reverse-proxy-caddy)
37. [Tâches planifiées (cron)](#37-tâches-planifiées-cron)

**Partie VIII : Fonctionnalités**
38. [Vue d'ensemble (dashboard)](#38-vue-densemble-dashboard)
39. [Gestion des clients](#39-gestion-des-clients)
40. [Journal des connexions](#40-journal-des-connexions)
41. [Monitoring](#41-monitoring)
42. [Alertes](#42-alertes)
43. [Conformité](#43-conformité)
44. [Système](#44-système)
45. [Réglages](#45-réglages)
46. [Utilisateurs et rôles](#46-utilisateurs-et-rôles)
47. [Tokens API](#47-tokens-api)
48. [Aide intégrée](#48-aide-intégrée)
49. [Fonctionnalités transverses](#49-fonctionnalités-transverses)

**Partie IX : Sécurité**
50. [Modèle d'authentification](#50-modèle-dauthentification)
51. [Contrôle d'accès par rôle (RBAC)](#51-contrôle-daccès-par-rôle-rbac)
52. [Protection des données et RGPD](#52-protection-des-données-et-rgpd)
53. [Traçabilité et audit](#53-traçabilité-et-audit)
54. [Checklist de durcissement](#54-checklist-de-durcissement)

**Partie X : Référence API**
55. [Authentification des appels API](#55-authentification-des-appels-api)
56. [Catalogue des endpoints](#56-catalogue-des-endpoints)

**Partie XI : Exploitation**
57. [Sauvegardes et rétention](#57-sauvegardes-et-rétention)
58. [Mise à jour de la plateforme](#58-mise-à-jour-de-la-plateforme)
59. [Supervision de la plateforme elle-même](#59-supervision-de-la-plateforme-elle-même)
60. [Capacité et dimensionnement](#60-capacité-et-dimensionnement)

**Partie XII : Dépannage**
61. [Méthodologie générale](#61-méthodologie-générale)
62. [Incidents courants](#62-incidents-courants)

**Partie XIII : Limites connues et feuille de route**
63. [Hors périmètre assumé](#63-hors-périmètre-assumé)
64. [Feuille de route](#64-feuille-de-route)

**Annexes**
65. [Glossaire](#65-glossaire)
66. [Aide-mémoire des commandes](#66-aide-mémoire-des-commandes)
67. [Licence](#67-licence)

---

# Partie I : Comprendre WireGuard

## 1. Qu'est-ce que WireGuard

**WireGuard** est un protocole et une implémentation logicielle de réseau privé virtuel (VPN) conçus pour être **simples, rapides et modernes en matière de cryptographie**. Créé par **Jason A. Donenfeld** et publié pour la première fois en 2016, WireGuard a été intégré au noyau Linux officiel à partir de la version **5.6** (mars 2020) : une reconnaissance rare pour un projet aussi jeune, saluée publiquement par Linus Torvalds pour la qualité de son code.

Contrairement aux VPN traditionnels (IPsec, OpenVPN) qui ont accumulé des décennies d'extensions, d'options de configuration et de modes de compatibilité, WireGuard part d'une feuille blanche avec un objectif unique : **faire une seule chose, et la faire extrêmement bien**. Le résultat tient dans environ **4 000 lignes de code** : contre plus de **400 000 lignes** pour OpenSSL/OpenVPN ou StrongSwan/IPsec. Cette compacité n'est pas un détail esthétique : un code plus petit est un code plus facile à auditer, avec une surface d'attaque considérablement réduite.

> **Repère :** un utilisateur avec de solides connaissances en systèmes peut lire et comprendre l'intégralité du code source de WireGuard en une journée. C'est structurellement impossible avec OpenVPN ou IPsec.

### Positionnement technique

WireGuard opère à la **couche 3** (réseau) du modèle OSI. Il crée une interface réseau virtuelle (`wg0` par exemple) qui se comporte comme n'importe quelle autre interface réseau du système : on peut lui assigner une adresse IP, des routes, des règles de pare-feu. Le trafic qui entre dans cette interface est chiffré et encapsulé dans des paquets **UDP** avant d'être envoyé sur le réseau physique ; à l'arrivée, le paquet est déchiffré et présenté à l'interface comme un paquet IP normal.

---

## 2. Pourquoi WireGuard : comparaison avec IPsec et OpenVPN

| Critère | WireGuard | OpenVPN | IPsec/IKEv2 |
|---|---|---|---|
| Taille du code source | ~4 000 lignes | ~400 000+ lignes (avec OpenSSL) | ~600 000+ lignes |
| Emplacement d'exécution | Noyau Linux (module natif depuis 5.6) | Espace utilisateur | Noyau (démon userspace pour IKE) |
| Suite cryptographique | Fixe, moderne, non négociable | Configurable (risque de mauvaise configuration) | Configurable (risque de mauvaise configuration) |
| Négociation de protocole | Aucune (pas de "cipher suite negotiation") | Oui (source de vulnérabilités historiques) | Oui (source de vulnérabilités historiques) |
| Performance | Très élevée (latence/débit proches du natif) | Modérée (overhead espace utilisateur + TLS) | Élevée, mais configuration complexe |
| Vitesse d'établissement du tunnel | Millisecondes | Plusieurs centaines de ms (poignée de main TLS) | Variable, plusieurs échanges |
| Roaming (Wi-Fi → 4G) | Natif et transparent | Reconnexion nécessaire | Reconnexion nécessaire (MOBIKE limite le problème) |
| Configuration | Fichier `.conf` minimal (clé + endpoint) | Fichiers complexes (certificats, TLS, options) | Complexe (policies, proposals, PSK/certificats) |
| Surface exposée sans authentification | Aucune (paquets non authentifiés ignorés) | Port ouvert, poignée de main TLS visible | Port ouvert, échanges IKE visibles |
| Audit de sécurité | Formellement vérifié (preuves du protocole Noise) | Dépend de la configuration OpenSSL | Dépend de l'implémentation |

### Le principe du « silence radio »

L'une des propriétés de sécurité les plus notables de WireGuard est que le serveur **ne répond jamais** à un paquet non authentifié avec une clé autorisée. Un scan `nmap` sur un serveur WireGuard ne révèle **rien** : le port UDP paraît filtré, indiscernable d'un port fermé. C'est une sécurité par **minimisation de la surface d'attaque**, intégrée au protocole lui-même plutôt que reposant uniquement sur un pare-feu.

---

## 3. Fondations cryptographiques

WireGuard repose sur le **Noise Protocol Framework**, un cadre de conception de protocoles cryptographiques créé par Trevor Perrin (également à l'origine du protocole utilisé par Signal). Plutôt qu'un catalogue d'algorithmes interchangeables, WireGuard fait des choix fermes, tous considérés comme état de l'art :

| Fonction | Algorithme | Rôle |
|---|---|---|
| Échange de clés | **Curve25519** (ECDH) | Établit un secret partagé sans jamais transmettre la clé privée |
| Chiffrement symétrique | **ChaCha20** | Chiffre le trafic du tunnel : rapide même sans accélération matérielle AES |
| Authentification des messages | **Poly1305** | Garantit qu'un paquet n'a pas été altéré en transit |
| Fonction de hachage | **BLAKE2s** | Utilisée dans la dérivation de clés et la poignée de main |
| Dérivation de clé | **HKDF** | Dérive les clés de session à partir du secret partagé |
| Résistance au rejeu | **Compteurs + fenêtre glissante** | Empêche la réinjection d'un paquet capturé |

Ce choix figé élimine toute une classe de vulnérabilités liées à la négociation de protocole (*downgrade attacks*), qui a historiquement touché TLS/SSL et donc OpenVPN (POODLE, BEAST...). Avec WireGuard, il n'y a rien à négocier, donc rien à dégrader.

### La poignée de main (handshake)

WireGuard utilise une poignée de main en une seule paire de messages (**1-RTT**), basée sur le motif Noise `IKpsk2`, qui fournit :
- **Confidentialité persistante** (*forward secrecy*) : une nouvelle paire de clés éphémères est générée à chaque poignée de main (renouvelée automatiquement toutes les 2 minutes), donc la compromission d'une clé à long terme ne permet pas de déchiffrer les communications passées ;
- **Authentification mutuelle** : chaque partie prouve la possession de sa clé privée sans la révéler ;
- **Résistance aux attaques par rejeu et par déni de service**, grâce à un mécanisme de "cookies" comparable à celui de TCP SYN.

---

## 4. Fonctionnement technique : Cryptokey Routing

Le concept central de WireGuard est le **Cryptokey Routing** (routage par clé cryptographique). Chaque interface WireGuard maintient une table simple qui associe :

```
Clé publique d'un pair  ⟷  Liste d'adresses IP autorisées (AllowedIPs)
```

Quand un paquet sortant doit être envoyé vers une IP donnée, WireGuard consulte cette table pour déterminer **avec quelle clé publique le chiffrer**. Quand un paquet arrive et se déchiffre avec succès via la clé d'un pair, WireGuard vérifie que l'IP source du paquet déchiffré correspond aux `AllowedIPs` déclarés pour ce pair : sinon il est silencieusement rejeté.

Ce mécanisme unifie en une seule table ce qui nécessite, en IPsec, plusieurs concepts distincts (Security Associations, Security Policy Database, routage). C'est ce qui permet à une configuration WireGuard de tenir en une dizaine de lignes :

```ini
[Interface]
PrivateKey = <clé privée du client>
Address = 10.66.66.2/32

[Peer]
PublicKey = <clé publique du serveur>
AllowedIPs = 0.0.0.0/0
Endpoint = vpn.exemple.com:51820
PersistentKeepalive = 25
```

### Le rôle du serveur : un pair parmi d'autres

Conceptuellement, WireGuard ne distingue pas "serveur" et "client" : ce sont tous des **pairs** (*peers*), chacun avec sa propre paire de clés. Ce qu'on appelle usuellement "serveur" est simplement le pair qui écoute sur un port connu et dont l'`Endpoint` est fixe ; les "clients" ont une IP publique qui peut changer (roaming). Cette symétrie rend WireGuard pertinent aussi bien en **site-à-site** qu'en **accès distant** ou en **maillage** entre serveurs.

---

## 5. Avantages et limites

### Avantages

- **Performance** : overhead minimal, exécution en espace noyau, chiffrement optimisé pour le matériel moderne.
- **Simplicité** : configuration réduite au strict nécessaire, aucun arbre de décision cryptographique.
- **Sécurité par conception**, pas de négociation de protocole, forward secrecy native, code auditable.
- **Roaming transparent** : un client change de réseau (Wi-Fi → 4G → Ethernet) sans jamais rompre sa session applicative.
- **Empreinte réduite** : adapté aux environnements contraints (routeurs, IoT, mobile) sans sacrifier la sécurité.
- **Cryptokey Routing** : un modèle mental unique et cohérent pour le routage et la sécurité.

### Limites et points de vigilance

- **Pas d'authentification utilisateur native** : WireGuard authentifie des **clés**, pas des personnes. L'association « quelle clé appartient à quelle personne » doit être gérée en dehors du protocole : c'est précisément le rôle qu'assure BLOCKHash (Partie II).
- **Pas d'attribution d'adresse IP dynamique** (pas de DHCP) : les adresses sont statiques par pair, ce qui impose une gestion d'allocation (également prise en charge par BLOCKHash).
- **Confidentialité des métadonnées limitée** : comme tout VPN UDP, le volume et le rythme du trafic restent observables par un intermédiaire réseau, même si le contenu est chiffré.
- **Pas de révocation en temps réel dans le protocole** : révoquer un pair signifie le retirer de la configuration ; il n'existe pas de liste de révocation façon PKI X.509. Là encore, c'est à l'outillage (BLOCKHash) de combler ce manque par une gestion opérationnelle rigoureuse.

---

## 6. Cas d'usage type en entreprise

| Cas d'usage | Description |
|---|---|
| **Accès distant sécurisé** | Remplacement d'un VPN d'entreprise classique pour permettre aux collaborateurs de rejoindre le réseau interne depuis n'importe où. |
| **Interconnexion site-à-site** | Relier deux datacenters, deux bureaux, ou un datacenter et un environnement cloud, avec chiffrement de bout en bout. |
| **Bastion réseau administrateur** | Restreindre l'accès SSH/RDP aux serveurs de production à des IP uniquement joignables via le tunnel : le modèle déployé par ce projet. |
| **Maillage multi-cloud** | Connecter des ressources hébergées chez plusieurs fournisseurs (Azure, AWS, GCP, on-premise) dans un réseau privé unique. |
| **Sécurisation IoT / Edge** | Faible empreinte CPU/mémoire, adapté aux appareils contraints (Raspberry Pi, routeurs embarqués). |
| **Environnements réglementés** | Auditabilité du code et cryptographie non négociable, appréciées en finance, santé, secteur public. |

---

# Partie II : Qu'est-ce que BLOCKHash

## 7. Présentation générale

**BLOCKHash** est une plateforme complète qui transforme un serveur WireGuard « nu » en une **console d'administration VPN de niveau entreprise**. Le projet comprend deux couches indissociables :

1. **La couche infrastructure** : provisionnement Azure via Terraform, installation et durcissement du serveur WireGuard, scripts d'exploitation en ligne de commande.
2. **La couche applicative** : un dashboard web (backend Flask + frontend HTML/CSS/JS) qui pilote ce serveur WireGuard au travers d'une interface graphique complète : création et cycle de vie des clients, supervision temps réel, alerting, sauvegardes, conformité, comptes utilisateurs à rôles, tokens API, etc.

Le nom du projet reflète sa fonction : **BLOCK**ing/monitoring pour WireGuard, avec une architecture qui s'appuie fortement sur le **Hash**ing (jetons, mots de passe, intégrité des sauvegardes).

## 8. Proposition de valeur

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

## 9. Ce que BLOCKHash n'est pas

Par souci de transparence (voir aussi la Partie XIII) :

- **Ce n'est pas un fournisseur d'identité d'entreprise.** BLOCKHash gère ses propres comptes utilisateurs ; il ne s'intègre pas (encore) à un SSO/LDAP/Active Directory/OIDC externe.
- **Ce n'est pas une solution multi-tenant SaaS.** Le projet est conçu pour être déployé et exploité par une seule organisation, sur sa propre infrastructure.
- **Ce n'est pas un WAF ni un IDS/IPS.** La sécurité réseau périmétrique (NSG, pare-feu OS) reste de la responsabilité de l'infrastructure sous-jacente, documentée en Partie VI.

---

# Partie III : Architecture

## 10. Vue d'ensemble de l'architecture

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

## 11. Composants du système

| Composant | Rôle | Exécuté en tant que |
|---|---|---|
| **Module noyau `wireguard`** | Chiffrement/déchiffrement du trafic, gestion de l'interface `wg0` | Noyau (root) |
| **`wgctl.py`** | Logique privilégiée de gestion du cycle de vie des clients (ajout, activation, renommage, révocation, régénération de clés, contact/RGPD) | root, invoqué via `sudo -n` par www-data |
| **`wgops.py`** | Opérations système privilégiées (sauvegardes, restauration, rotation des clés serveur, redémarrage du tunnel, export, diagnostic) | root, invoqué via `sudo -n` par www-data |
| **`app.py` (Flask)** | API HTTP (73 routes), authentification, autorisation par rôle, orchestration | www-data, sans privilège root |
| **Gunicorn** | Serveur d'application WSGI, 2 workers en mode **gevent** (coroutines) | www-data |
| **Caddy** | Reverse proxy HTTPS, terminaison TLS, sert le frontend statique | root (bind sur le port 443), ou www-data selon le durcissement |
| **SQLite (`blockhash.db`)** | Persistance des métriques, logs de connexion, alertes, utilisateurs, sessions, tokens API, abonnements Web Push | Écrit par **www-data ET root** (voir §14) |
| **Cron (root)** | Capture périodique de l'état WireGuard, purge, évaluation des alertes, vérification des expirations, sauvegardes planifiées | root |

## 12. Flux réseau et ports

| Port | Protocole | Usage | Exposition |
|---|---|---|---|
| 51820 (configurable) | UDP | Tunnel WireGuard | Publique (Internet) |
| 443 | TCP | Dashboard (HTTPS via Caddy) | Publique, restreinte par NSG à l'IP admin si souhaité |
| 22 | TCP | SSH d'administration de la VM | Publique, restreinte par NSG à l'IP admin |
| 8080 | TCP | Gunicorn (backend Flask) | **Local uniquement** (`127.0.0.1`), jamais exposé directement |

## 13. Cycle de vie d'une connexion client

1. Le client WireGuard initie une poignée de main UDP vers l'`Endpoint` du serveur.
2. Le noyau Linux (module `wireguard`) authentifie et déchiffre les paquets suivants sans intervention applicative.
3. Toutes les 5 minutes, un script cron exécuté en root interroge `wg show wg0 dump`, calcule les deltas de trafic (octets reçus/émis depuis le dernier échantillon) et les insère dans `blockhash.db`.
4. Le flux **Server-Sent Events** (`/api/events/stream`) compare l'état courant à l'état précédent à chaque itération (toutes les 3 secondes) et pousse un événement `peer_connected`/`peer_disconnected` à tous les onglets ouverts dès qu'une transition est détectée.
5. Si une règle d'alerte correspond à la transition (ex. connexion hors horaires), une notification est déclenchée sur les canaux configurés (email, Slack, Discord, Telegram, Web Push).
6. L'historique de connexion reste consultable dans la page **Journal**, avec filtres, pagination et heatmap.

## 14. Modèle de séparation des privilèges

BLOCKHash applique le principe du **moindre privilège** de bout en bout :

- Le processus Flask (`app.py`) tourne **sans aucun privilège root**, sous l'utilisateur système `www-data`.
- Toute opération nécessitant un accès root (lecture de l'état WireGuard, écriture dans `/etc/wireguard/`, redémarrage du tunnel, rotation de clés) passe **exclusivement** par deux scripts dédiés, `wgctl.py` et `wgops.py`, invoqués via une règle `sudo -n` strictement scoped (pas de mot de passe interactif, pas d'accès shell).
- Un attaquant qui compromettrait le processus Flask n'obtient **pas** automatiquement un accès root : il est limité aux actions explicitement exposées par ces deux scripts, elles-mêmes validées côté Flask (nom de client, chemin de sauvegarde, etc.) avant l'appel privilégié.

> **Point d'attention opérationnel documenté :** certaines données (sessions utilisateur, comptes, tokens API, alertes) sont désormais écrites par **le processus www-data lui-même**, alors que la base SQLite historique n'était pensée que pour un écrivain root (le cron de capture). Le fichier est donc configuré en mode `0660` avec le bit **setgid** posé sur son répertoire parent, pour que les deux écrivains (root et www-data) y aient un accès garanti dans la durée. Voir Partie XII, [§62](#62-incidents-courants), pour le détail de cet arbitrage.

---

# Partie IV : Stack technique

## 15. Infrastructure

| Technologie | Usage dans le projet |
|---|---|
| **Terraform** (>= 1.5) | Infrastructure-as-Code : provisionnement complet de l'environnement Azure (réseau, VM, NSG, disques) en modules réutilisables |
| **Microsoft Azure** | Fournisseur cloud cible (groupe de ressources, réseau virtuel, VM, IP publique) |
| **cloud-init** | Bootstrap de la VM à la création (fichier `cloud-init.yaml.tpl`), pour une configuration reproductible dès le premier démarrage |

## 16. Système et réseau

| Technologie | Usage |
|---|---|
| **Ubuntu 22.04 LTS** | Système d'exploitation de la VM |
| **WireGuard** (module noyau + `wireguard-tools`) | Cœur du VPN (voir Partie I) |
| **systemd** | Gestion du service `wg-quick@wg0` et du service `blockhash-dashboard` |
| **Caddy** | Reverse proxy HTTPS, terminaison TLS (certificat interne auto-signé), HTTP/2, gestion dédiée du flux SSE |
| **cron** | Orchestration des tâches périodiques (capture d'état, purge, alertes, expirations, sauvegardes planifiées) |
| **logrotate** | Rotation des journaux CSV/texte |
| **ufw / iptables** | Durcissement du pare-feu local, en complément du NSG Azure |

## 17. Backend

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

## 18. Frontend

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

## 19. Dépendances complètes

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

# Partie V : Structure du projet

## 20. Vue d'ensemble de l'arborescence

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
    │   └── tests/                   ← suite de tests (606 lignes, voir §25)
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

## 21. `terraform/`

Provisionne l'intégralité de l'infrastructure Azure nécessaire, en **deux modules indépendants** :

- **`modules/network/`** : Réseau virtuel (`vnet-wireguard-lab`), sous-réseau dédié, groupe de sécurité réseau (`nsg-wireguard-lab`) avec quatre règles explicites : `AllowSSH-Admin`, `AllowWireGuard`, `AllowDashboard-Admin`, et une règle **`DenyAllOtherInbound`** en toute fin de chaîne (défense en profondeur : rien n'est autorisé par défaut).
- **`modules/compute/`** : Machine virtuelle (taille par défaut `Standard_B2s`), IP publique, disque, et injection d'un script `cloud-init.yaml.tpl` pour une préparation reproductible dès le premier démarrage.

Le fichier `terraform.tfvars.example` documente toutes les variables surchargeables (région, taille de VM, ports, IP autorisées, nom d'utilisateur admin...). Le script `deploy.ps1` encapsule le cycle `terraform init/plan/apply` pour les utilisateurs Windows/PowerShell.

## 22. `scripts/`

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

## 23. `dashboard/backend/`

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

## 24. `dashboard/frontend/`

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

## 25. `dashboard/backend/tests/`

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

# Partie VI : Déploiement

## 26. Prérequis

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

## 27. Étape 1 : Provisionner l'infrastructure Azure

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
# éditer terraform.tfvars : région, taille de VM, IP autorisées, nom d'utilisateur admin...
terraform init
terraform plan
terraform apply
```

Sous Windows/PowerShell, le script `deploy.ps1` encapsule ce cycle. À l'issue, Terraform affiche en sortie (`outputs.tf`) l'adresse IP publique de la VM et les informations de connexion SSH.

## 28. Étape 2 : Installer le serveur WireGuard

```bash
ssh wgadmin@<IP_PUBLIQUE>
sudo ./scripts/01-install-wireguard-server.sh
```

Ce script installe le paquet `wireguard`, génère la paire de clés du serveur, crée `/etc/wireguard/wg0.conf`, configure le forwarding IP et active `wg-quick@wg0` au démarrage.

## 29. Étape 3 : Créer et distribuer des clients

```bash
sudo ./scripts/02-add-client.sh alice-laptop
```

Le script génère la paire de clés du client, alloue une adresse IP dans le sous-réseau du tunnel, et affiche/enregistre le fichier `.conf` prêt à être importé dans l'application WireGuard officielle (ou scanné via QR code une fois le dashboard installé : voir Partie VIII).

## 30. Étape 4 : Installer le dashboard BLOCKHash

```bash
# Copier le dossier dashboard/ sur la VM, puis :
sudo ./scripts/03-install-dashboard.sh
```

Ce script réalise, dans l'ordre :
1. Création du répertoire applicatif (`/opt/blockhash-dashboard`), de l'environnement virtuel Python et installation des dépendances (`requirements.txt`).
2. Génération d'un jeton d'authentification (`DASHBOARD_TOKEN`), d'un nom d'utilisateur et d'un mot de passe administrateur, écrits dans `/etc/blockhash/dashboard.env`.
3. Création du service systemd `blockhash-dashboard` (Gunicorn, 2 workers `gevent`).
4. Mise en place d'une règle `sudo -n` étroitement scoped pour que `www-data` puisse invoquer `wgctl.py`/`wgops.py` sans mot de passe interactif ni accès shell.
5. Configuration de Caddy comme reverse proxy HTTPS (TLS interne auto-signé), avec un bloc dédié au flux SSE (`flush_interval -1`, pas de compression).
6. Application des permissions sur `/var/log/wireguard` : propriétaire/groupe `www-data`, **bit setgid** (voir §14 et §62).

À l'issue, l'identifiant et le mot de passe administrateur générés sont affichés **une seule fois** dans le terminal : à noter immédiatement dans un gestionnaire de secrets.

## 31. Étape 5 : Journalisation, monitoring et tâches planifiées

```bash
sudo ./scripts/04-logging-monitoring.sh
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

## 32. Étape 6 : Valider le déploiement

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

# Partie VII : Configuration de référence

## 33. Variables d'environnement

Fichier `/etc/blockhash/dashboard.env`, chargé par le service systemd :

| Variable | Rôle | Valeur par défaut |
|---|---|---|
| `DASHBOARD_TOKEN` | Jeton d'authentification historique (rétro-compatibilité, voir Partie IX) | généré à l'installation |
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
| `SETTINGS_PATH`, `ALERTS_CONFIG_PATH`, `REPORTS_CONFIG_PATH`, `SERVERS_CONFIG_PATH` | Fichiers JSON de configuration persistée | voir §34 |
| `BLOCKHASH_CONFIG_DIR` | Répertoire des clés VAPID (Web Push) | `/etc/blockhash` |
| `VAPID_CONTACT_EMAIL` | Adresse de contact incluse dans les revendications VAPID | `mailto:admin@example.com` |
| `GEOIP_TTL_SEC` | Durée de mise en cache des résolutions GeoIP | selon `geoip.py` |
| `FRONTEND_DIR`, `PORT` | Chemin du frontend statique et port d'écoute de Gunicorn | `$APP_DIR/frontend`, `8080` |

## 34. Fichiers de configuration persistés

| Fichier | Contenu |
|---|---|
| `/etc/blockhash/dashboard-settings.json` | Réglages généraux : seuil « en ligne », rétention, format de date, fuseau horaire, langue, notifications desktop, planning de sauvegardes, politiques de conformité |
| `/etc/blockhash/alerts-config.json` | Configuration complète du moteur d'alertes : règles activées, cooldowns, canaux (SMTP, Slack, Discord, Telegram, Web Push) |
| `/etc/blockhash/reports-config.json` | Configuration du rapport hebdomadaire (activation, destinataire) |
| `/etc/blockhash/servers.json` | Registre multi-serveurs (le cas échéant) |
| `/etc/blockhash/vapid_private_key.pem` | Clé privée VAPID (Web Push), générée automatiquement au premier envoi, permissions `0600` |

## 35. Service systemd

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

Le worker `gevent` (plutôt que le worker synchrone par défaut ou `gthread`) est **indispensable** : le flux SSE maintient une connexion HTTP ouverte en continu par onglet client ; un worker à base de threads OS saturerait rapidement son pool dès quelques onglets ouverts simultanément (voir Partie XII pour le détail de cet incident et de sa correction).

## 36. Reverse proxy Caddy

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

## 37. Tâches planifiées (cron)

| Fréquence | Commande | Rôle |
|---|---|---|
| Toutes les 5 min | Script de capture (`04-logging-monitoring.sh`) | Insère un échantillon de débit par client dans SQLite |
| Toutes les 5 min | `09-check-alerts.sh` | Évalue les règles d'alerte (inactivité, bande passante, service, expiration, seuils système, nouvelle IP) |
| Nuit (3h30) | `store.py prune` | Purge les données (logs, échantillons, alertes) au-delà de la rétention configurée |
| Nuit (4h) | `wgops.py auto-backup` | Sauvegarde planifiée, auto-limitée selon le planning configuré dans Réglages (désactivé/quotidien/hebdomadaire/mensuel) |
| Nuit | `07-check-expirations.sh` | Désactive automatiquement les clients dont la date d'expiration est dépassée |

---

# Partie VIII : Fonctionnalités

BLOCKHash est organisé en **onze sections** accessibles depuis la barre de navigation latérale. Cette partie documente chaque fonctionnalité de façon exhaustive.

## 38. Vue d'ensemble (dashboard)

- Compteurs en temps réel : clients configurés, en ligne, inactifs, désactivés.
- Répartition des statuts (graphique).
- Débit du tunnel (graphique temps réel).
- Clients connectés, avec durée de connexion.
- Expirations à venir.
- Activité récente (flux d'événements).
- Actions rapides (accès direct aux tâches courantes).

## 39. Gestion des clients

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

## 40. Journal des connexions

- Historique paginé au niveau base de données (aucune limite de volume affichable).
- Recherche texte (client, IP, endpoint), filtre par statut.
- Filtres avancés : plage de dates, volume minimal/maximal.
- Recherches sauvegardées (rappel rapide d'une combinaison de filtres).
- Détail d'une session en un clic (endpoint complet, volumes, clé publique).
- **Heatmap des connexions** (créneaux horaires × jours de la semaine, 30 derniers jours).
- Export CSV de la page courante.

## 41. Monitoring

- Graphique de débit long terme, avec **zoom molette et pan par glisser**.
- Métriques hôte : CPU, mémoire, disque, connexions TCP actives, latence réseau (à la demande), température CPU (si le matériel l'expose).
- Carte de géolocalisation des endpoints (GeoIP approximatif), avec **top 10 des pays** représentés.
- Détection d'anomalies de débit.
- État des services surveillés (`wg-quick@wg0`, `blockhash-dashboard`).

## 42. Alertes

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

## 43. Conformité

- Détection des clients inactifs au-delà d'un seuil, avec **politiques par tag** (ex. `#vip` : 180 jours, `#externe` : 30 jours) et liste d'exceptions documentées.
- Export d'un rapport PDF de conformité.
- Rapport hebdomadaire automatique par e-mail (activable, configurable).

## 44. Système

- **Sauvegardes** : création manuelle avec description libre, planification (désactivé/quotidien/hebdomadaire/mensuel, auto-limitée sans droit d'écriture sur la crontab pour `www-data`), intégrité vérifiée par empreinte **SHA-256**, téléchargement protégé par re-saisie du mot de passe (avec anti force-brute dédié), **restauration à double confirmation** (mot de passe + saisie du mot « RESTORE »), sauvegarde de sécurité automatique de l'état courant avant toute restauration.
- **Diagnostic** : état du service `wg-quick`, interface WireGuard active, connectivité réseau sortante, espace disque, permissions des fichiers critiques : rapport consultable depuis l'interface.
- **Journal d'audit** : aperçu des 5 dernières actions sur la page Système, page dédiée avec filtres complets (action, IP, plage de dates) et export.
- **Opérations** : redémarrage du tunnel et rotation des clés serveur, avec aperçu du nombre de clients impactés avant confirmation, et entrée systématique au journal d'audit.
- **Export global** : archive ZIP de l'ensemble des configurations clients.

## 45. Réglages

- Seuil de détection « en ligne », rétention des données (avec purge manuelle immédiate en plus de la purge automatique nocturne).
- Notifications desktop (Notification API) et **Web Push** (abonnement/désabonnement, test).
- Format de date, fuseau horaire, langue (FR/EN).
- Politiques de conformité par tag (voir §43).
- Thème clair / sombre / automatique (suit les préférences système, mise à jour en direct).

## 46. Utilisateurs et rôles

- Comptes nominatifs avec trois rôles : **lecteur** (consultation), **opérateur** (+ gestion des clients), **admin** (accès complet, y compris opérations système et gouvernance des comptes).
- CRUD complet : création, modification (rôle, statut actif/inactif, réinitialisation de mot de passe), suppression.
- Garde-fou intégré : impossible de supprimer ou de rétrograder le **dernier compte admin actif**.
- Page dédiée, réservée aux comptes admin.

## 47. Tokens API

- Génération de tokens nommés, avec **scope** (lecture / écriture / admin) et expiration optionnelle.
- Le token en clair n'est affiché **qu'une seule fois** à la création (seule son empreinte est stockée en base).
- Liste des tokens actifs (créateur, dernière utilisation, expiration), révocation immédiate.
- Page dédiée, réservée aux comptes admin.

## 48. Aide intégrée

- Page dédiée avec sept fiches procédurales pas-à-pas : créer un client, importer en masse, télécharger une configuration, consulter les logs, créer une alerte, restaurer une sauvegarde, gérer les utilisateurs.

## 49. Fonctionnalités transverses

- **Temps réel** : mise à jour de l'ensemble du dashboard via Server-Sent Events, sans rafraîchissement de page.
- **Internationalisation** : interface statique disponible en français et anglais.
- **Thème** : clair / sombre / automatique.
- **Recherche globale** et **raccourcis clavier** (`g c` / `g a` / `g m` pour naviguer, `/` pour rechercher, `?` pour l'aide, `Échap` pour fermer une fenêtre modale).
- **Mode démonstration** : le dashboard peut être exploré sans connexion API réelle, à partir d'un jeu de données d'exemple.
- **Responsive** : utilisable sur mobile et tablette.
- **Assistant de premier lancement** : vérifications de bon fonctionnement à la première connexion.
- **Signalement** : bouton d'envoi de retour/bug pré-rempli avec le contexte technique.

---

# Partie IX : Sécurité

## 50. Modèle d'authentification

BLOCKHash distingue trois mécanismes d'authentification, tous vérifiés par une fonction centrale (`check_auth()` dans `app.py`) :

1. **Comptes utilisateurs nominatifs** : `/api/login` échange un couple identifiant/mot de passe contre un **jeton de session** propre à l'utilisateur (aléatoire, haché en SQLite, jamais stocké en clair), valable par défaut 30 jours.
2. **Tokens API** : jetons nommés et scopés, créés depuis la page **Tokens API**, pour l'automatisation. Le jeton en clair n'est affiché qu'à sa création.
3. **Jeton historique partagé (`DASHBOARD_TOKEN`)** : conservé pour la rétrocompatibilité avec les déploiements antérieurs au modèle multi-utilisateurs ; traité comme un accès admin implicite. **Recommandation** : le désactiver (retirer la variable de `dashboard.env`) une fois la migration vers des comptes nominatifs terminée.

Le mot de passe est haché via `werkzeug.security` (scrypt/pbkdf2 selon version), jamais stocké en clair. Un mécanisme anti force-brute limite les tentatives de connexion par adresse IP (verrouillage temporaire configurable).

## 51. Contrôle d'accès par rôle (RBAC)

Trois rôles, avec une hiérarchie stricte :

| Rôle | Peut consulter | Peut modifier | Peut administrer |
|---|---|---|---|
| **reader** | Toutes les pages en lecture | N/A | N/A |
| **operator** | Tout ce que `reader` voit | Clients (création, édition, révocation, import), marquage des alertes | N/A |
| **admin** | Tout | Tout ce que `operator` peut faire | Réglages globaux, comptes utilisateurs, tokens API, opérations système, sauvegardes, signalements |

La vérification est appliquée à **deux niveaux**, volontairement redondants :
- **Backend** (`auth.required_role_for(method, path)`) : la seule source de vérité réelle pour la sécurité ; chaque requête API est évaluée avant exécution.
- **Frontend** : les boutons et sections réservés à un rôle supérieur sont masqués dynamiquement (attribut `data-role-min`), pour une expérience cohérente plutôt qu'un message d'erreur après un clic. Le masquage frontend est un confort d'usage, **jamais** un mécanisme de sécurité à lui seul.

## 52. Protection des données et RGPD

- Champs de contact client (nom, e-mail, téléphone, adresse, fonction) et **consentement horodaté**.
- Export complet des données d'un client (profil + historique de connexion) au format JSON, en réponse à une demande d'accès.
- Politiques de rétention et de purge automatique configurables.
- Aucune donnée transmise à un service tiers sans configuration explicite (les canaux d'alerte : e-mail, Slack, Discord, Telegram, Web Push : sont tous opt-in et configurés par l'organisation elle-même).

## 53. Traçabilité et audit

- **Journal d'audit** append-only (`/var/log/wireguard/audit.log`) : toute action de modification (création/révocation de client, connexion, échec d'authentification, rotation de clés, restauration, gestion des comptes...) y est consignée avec horodatage, IP source et détail structuré.
- Consultable depuis l'interface (aperçu + page dédiée avec filtres), exportable.
- **Signalements de bugs** eux-mêmes tracés (auteur, catégorie, sévérité, statut de traitement).

## 54. Checklist de durcissement

- [ ] Restreindre les règles NSG `AllowSSH-Admin` et `AllowDashboard-Admin` à des plages d'IP connues plutôt qu'à `Internet`.
- [ ] Désactiver `DASHBOARD_TOKEN` une fois tous les comptes/tokens nominatifs en place.
- [ ] Remplacer le certificat TLS interne auto-signé de Caddy par un certificat émis par une autorité reconnue (interne à l'organisation ou publique) si le dashboard est exposé au-delà d'un cercle restreint.
- [ ] Activer les alertes `failed_auth_attempts` et `off_hours`.
- [ ] Configurer un canal de notification (e-mail a minima) pour être alerté en cas d'événement critique.
- [ ] Vérifier régulièrement le journal d'audit et la boîte de réception des signalements.
- [ ] Maintenir à jour le système d'exploitation, le noyau (module WireGuard), et les dépendances Python (`requirements.txt`).
- [ ] Sauvegarder `wg0.conf` et la base SQLite en dehors de la VM (voir Partie XI).

---

# Partie X : Référence API

## 55. Authentification des appels API

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

## 56. Catalogue des endpoints

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

# Partie XI : Exploitation

## 57. Sauvegardes et rétention

- **Sauvegardes de configuration** (`wg0.conf`) : création manuelle avec description, planification automatique (désactivée par défaut), intégrité vérifiée par SHA-256, conservation des `WG_MAX_BACKUPS` (50 par défaut) plus récentes.
- **Restauration** : double confirmation (mot de passe + saisie de « RESTORE »), avec sauvegarde de sécurité automatique de l'état courant avant toute écrasement.
- **Rétention des données applicatives** (logs, métriques, alertes) : purge automatique nocturne selon `METRICS_RETENTION_DAYS`, purge manuelle immédiate disponible depuis Réglages.
- **Recommandation** : répliquer périodiquement `/etc/wireguard/backups/` et `/var/log/wireguard/blockhash.db` vers un stockage hors VM (snapshot de disque Azure, ou synchronisation externe).

## 58. Mise à jour de la plateforme

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

## 59. Supervision de la plateforme elle-même

- Page **Système > Diagnostic** : état du service `wg-quick`, connectivité sortante, espace disque, permissions.
- Page **Système > Journal d'audit** : détection d'activité anormale (échecs d'authentification répétés, actions hors horaires).
- `journalctl -u blockhash-dashboard -f` pour les logs applicatifs en direct.
- Alerte `service_down` (voir Partie VIII, §42) pour être notifié si `wg-quick@wg0` ou `blockhash-dashboard` s'arrête.

## 60. Capacité et dimensionnement

| Facteur | Recommandation |
|---|---|
| Nombre de clients WireGuard | Quelques centaines sans ajustement particulier (le goulot est le CPU de chiffrement, pas le dashboard) |
| Connexions dashboard simultanées (onglets ouverts, flux SSE) | Le worker `gevent` gère plusieurs centaines de connexions SSE concurrentes par worker (2 workers par défaut) sans épuisement de threads |
| Taille de la VM | `Standard_B2s` convient pour un usage PME ; passer à une taille supérieure si le nombre de clients ou la fréquence des rapports/alertes est élevé |
| Base SQLite | Adaptée jusqu'à plusieurs millions de lignes avec une rétention raisonnable (35 jours par défaut) ; au-delà, envisager une purge plus agressive |

---

# Partie XII : Dépannage

## 61. Méthodologie générale

1. Vérifier l'état des services : `systemctl status blockhash-dashboard wg-quick@wg0 caddy`.
2. Consulter les logs applicatifs : `journalctl -u blockhash-dashboard -n 100 --no-pager`.
3. Tester l'API en local, en s'affranchissant du reverse proxy : `curl -sk https://127.0.0.1/healthz`.
4. Vérifier les permissions des fichiers partagés entre root et www-data (voir incident ci-dessous).
5. Utiliser la page **Système > Diagnostic** du dashboard lui-même.

## 62. Incidents courants

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

**Cause.** Utilisation du worker par défaut (synchrone) ou `gthread` avec un flux SSE ouvert en continu par onglet : le pool de threads s'épuise dès que quelques onglets restent ouverts. **Solution** : `--worker-class gevent`, seule option adaptée à un flux SSE de longue durée (voir Partie VII, §35).

### Le rapport hebdomadaire ou l'export PDF échoue sans message clair

- Vérifier que `fpdf2` est installé dans le venv : `pip show fpdf2`.
- Vérifier qu'un canal e-mail est configuré et testé (page **Alertes > Configurer les canaux**, bouton **Tester**) : le rapport hebdomadaire réutilise cette même configuration SMTP.
- Depuis cette révision, un échec d'envoi renvoie un code HTTP explicite (422) avec le motif exact, au lieu d'un succès silencieux à tort.

---

# Partie XIII : Limites connues et feuille de route

## 63. Hors périmètre assumé

Ces choix sont **documentés et délibérés**, pas des oublis :

| Fonctionnalité | Statut | Raison |
|---|---|---|
| SSO / LDAP / Active Directory / OIDC | Non implémenté | Nécessiterait une intégration à un fournisseur d'identité externe, hors périmètre d'un projet auto-hébergé de cette taille |
| Authentification à deux facteurs (2FA/TOTP) | Non implémenté | Techniquement compatible avec le modèle multi-utilisateurs actuel, mais volontairement reporté pour éviter de complexifier l'authentification avant sa stabilisation |
| Internationalisation du contenu généré côté serveur | Partiel | Les messages d'alerte, le journal d'audit et les erreurs API restent en français ; seule l'interface statique est traduite (FR/EN) |
| Vraie notification Web Push à grande échelle | Implémenté en best-effort | Repose sur le protocole standard (VAPID) sans infrastructure de file d'attente dédiée ; convient à un usage d'équipe, pas à des milliers d'abonnés |
| Multi-tenant | Non implémenté | Le projet est conçu pour une organisation unique |

## 64. Feuille de route

- Authentification à deux facteurs (TOTP) pour les comptes admin.
- Intégration SSO (OIDC a minima).
- Rétention et purge automatique différenciées par type de donnée (au-delà du réglage global actuel).
- Export/import chiffré de sauvegardes pour la reprise après sinistre cross-instance.

---

# Annexes

## 65. Glossaire

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

## 66. Aide-mémoire des commandes

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

## 67. Licence

Ce projet est distribué sous licence **MIT**. Voir le fichier [`LICENSE`](./LICENSE) pour le texte complet.

---

<div align="center">

*Documentation maintenue au fil des évolutions du projet : dernière refonte complète incluant l'authentification multi-utilisateurs, les tokens API scopés, le moteur d'alertes étendu, les notifications Web Push, l'internationalisation et le centre de signalement.*

</div>
