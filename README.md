# LAB WireGuard VPN- BLOCKHash
 
**Guide complet d'installation, de configuration et de supervision d'un serveur VPN WireGuard sur une VM Ubuntu dans Microsoft Azure.**
 
Ce document est un support de formation (TP) destiné aux professionnels et étudiants souhaitant maîtriser le déploiement d'une infrastructure VPN moderne, de l'infrastructure-as-code jusqu'à la supervision opérationnelle.

---

## Sommaire

1. [Présentation du LAB](#1-présentation-du-lab)
2. [Prérequis](#2-prérequis)
3. [Architecture](#3-architecture)
4. [Étape 1- Déploiement de l'infrastructure Azure](#4-étape-1--déploiement-de-linfrastructure-azure)
5. [Étape 2- Installation du serveur WireGuard](#5-étape-2--installation-du-serveur-wireguard)
6. [Étape 3- Création et distribution des clients](#6-étape-3--création-et-distribution-des-clients)
7. [Étape 4- Dashboard de supervision](#7-étape-4--dashboard-de-supervision)
8. [Étape 5- Journalisation et logs](#8-étape-5--journalisation-et-logs)
9. [Étape 6- Tests et validation du tunnel](#9-étape-6--tests-et-validation-du-tunnel)
10. [Commandes Linux de référence](#10-commandes-linux-de-référence)
11. [Durcissement et bonnes pratiques de sécurité](#11-durcissement-et-bonnes-pratiques-de-sécurité)
12. [Dépannage (Troubleshooting)](#12-dépannage-troubleshooting)
13. [Nettoyage / destruction du LAB](#13-nettoyage--destruction-du-lab)
14. [Annexe- Exercices pour les stagiaires](#14-annexe--exercices-pour-les-stagiaires)
15. [Licence et conditions de diffusion](#15-licence-et-conditions-de-diffusion)

---

## 1. Présentation du LAB

WireGuard est un protocole VPN moderne, léger (~4 000 lignes de code contre plusieurs centaines de milliers pour IPsec/OpenVPN), reposant sur une cryptographie de nouvelle génération (Curve25519, ChaCha20, Poly1305, BLAKE2s). Il est aujourd'hui intégré nativement au noyau Linux.

Ce LAB permet de reproduire, en environnement cloud isolé, un déploiement complet et réaliste :

- Provisionnement d'une infrastructure Azure via **Infrastructure as Code** (Terraform, en modules réutilisables)
- Installation et configuration d'un **serveur WireGuard** sur Ubuntu 22.04 LTS
- Génération et distribution de **configurations clients** (fichier `.conf` + QR code)
- Un **dashboard web maison** (HTML/CSS/JS + API Flask) de supervision des tunnels, avec journal pagine et interrogeable en SQL (recherche/tri/filtre), gestion complète du cycle de vie des clients (ajout, activation/désactivation, renommage, expiration, limitation de débit, révocation), **monitoring avancé** (débit long terme, ressources serveur, détection d'anomalies, carte GeoIP des endpoints), **alerting configurable** (email/Slack/Discord/Telegram), **administration système** (sauvegardes versionnées, rotation de clés, multi-serveurs), **reporting** (export CSV/PDF, rapport hebdomadaire, vue conformité), **mises à jour en temps réel** (Server-Sent Events) et une **interface soignée** (thème clair/sombre, recherche globale, mode NOC, vraiment responsive mobile)
- **Journalisation** des connexions (logs CSV, rotation, audit)
- Durcissement du pare-feu (NSG Azure + `ufw` + `iptables`)

**Public visé :** administrateurs systèmes, ingénieurs réseau, étudiants en cybersécurité, formateurs.

**Durée estimée du TP :** 2 à 3 heures.

---

## 2. Prérequis

| Élément | Détail |
|---|---|
| Abonnement Azure | Actif, avec droits de création de groupe de ressources |
| Terraform | CLI >= 1.5 ([téléchargement](https://developer.hashicorp.com/terraform/install)) |
| Azure CLI | `az` CLI installée et authentifiée (`az login`)- utilisée par le provider Terraform `azurerm` |
| Client SSH | OpenSSH (intégré à Windows 10/11, macOS, Linux) |
| Application WireGuard | [wireguard.com/install](https://www.wireguard.com/install/) sur le poste client (Windows/macOS/Linux/iOS/Android) |
| Connaissances de base | Ligne de commande Linux, notions de réseau (NAT, CIDR, ports) |

Vérifiez votre connexion à Azure avant de commencer si vous êtes en local :

```bash
az login
az account show
```

si vous êtes dan sle portail Azure lancez le Cloud Shell.

<img width="1540" height="431" alt="image" src="https://github.com/user-attachments/assets/d962187a-f522-4344-b53d-02c307cff626" />


---

## 3. Architecture

```
                         Internet
                             │
                             │  UDP 51820 (WireGuard)
                             │  TCP 22    (SSH admin)
                             │  TCP 8080  (Dashboard admin)
                             ▼
                 ┌───────────────────────────┐
                 │   Azure NSG : nsg-wireguard-lab │
                 └───────────────────────────┘
                             │
                 ┌───────────────────────────┐
                 │  VM Ubuntu 22.04 LTS          │
                 │  vm-wireguard-lab             │
                 │  10.10.0.10 (privée)          │
                 │                                │
                 │  ┌──────────────────────────┐  │
                 │  │ Interface wg0            │  │
                 │  │ 10.66.66.1/24            │  │
                 │  │ + peers clients (.2, .3…)│  │
                 │  └──────────────────────────┘  │
                 │                                │
                 │  Dashboard BLOCKHash (port 8080)│
                 │  Flask API + HTML/CSS/JS        │
                 │  Logs CSV (/var/log/wireguard)  │
                 └───────────────────────────┘
                             │
                 ┌───────────┴────────────┐
                 ▼                        ▼
          Client A (portable)      Client B (mobile)
          10.66.66.2               10.66.66.3
```

Ressources Azure créées (via Terraform) : 1 groupe de ressources, 1 VNet, 1 sous-réseau, 1 NSG, 1 IP publique statique avec DNS label, 1 interface réseau, 1 VM Ubuntu 22.04 LTS.

### Arborescence du projet

```
blockhash-wireguard-lab/
├── README.md
├── terraform/                    # Infrastructure as Code (remplace Bicep)
│   ├── main.tf                   # Racine : resource group + appel des modules
│   ├── variables.tf
│   ├── outputs.tf
│   ├── providers.tf
│   ├── terraform.tfvars.example
│   ├── deploy.ps1                # Assistant de déploiement (optionnel)
│   └── modules/
│       ├── network/               # VNet, subnet, NSG et règles
│       └── compute/                # IP publique, NIC, VM Ubuntu + cloud-init
├── scripts/
│   ├── 01-install-wireguard-server.sh
│   ├── 02-add-client.sh
│   ├── 03-install-dashboard.sh    # Déploie le dashboard BLOCKHash (Flask + frontend)
│   ├── 04-logging-monitoring.sh
│   ├── 05-revoke-client.sh
│   ├── 06-manage-client.sh        # CLI : activer/désactiver/renommer/expirer/limiter/régénérer/révoquer (voir 7.6)
│   ├── 07-check-expirations.sh    # Cron : désactive les clients dont l'expiration est dépassée
│   └── 09-check-alerts.sh         # Cron : évalue les règles d'alerte et notifie (voir 7.7.4)
└── dashboard/                      # Dashboard web maison
    ├── backend/                    # API Flask (lit wg show + tunnels.csv, pilote wgctl.py)
    │   ├── app.py
    │   ├── wgctl.py                # Logique privilégiée : gestion clients (voir 7.6.1)
    │   ├── wgops.py                # Logique privilégiée : opérations système (voir 7.8.1)
    │   ├── wgstate.py              # Lecture wg0.conf/wg show partagée, sans Flask
    │   ├── store.py                # SQLite : métriques, JOURNAL DES CONNEXIONS, alertes, cache GeoIP
    │   ├── settings_store.py       # Réglages ajustables à chaud (seuil "en ligne", etc.)
    │   ├── system_monitor.py       # CPU/RAM/disque (psutil) + statut des services systemd
    │   ├── anomalies.py            # Détection simple (pic de trafic, endpoint flapping)
    │   ├── alerts.py               # Moteur de notification (email/Slack/Discord/Telegram)
    │   ├── reports.py              # Export PDF générique + rapport hebdomadaire
    │   ├── servers_store.py        # Registre multi-serveurs (voir 7.8.5)
    │   ├── geoip.py                # Résolution IP -> position (carte des endpoints, voir 7.10.5)
    │   ├── tests/                  # Suite pytest (voir 7.10.6)
    │   ├── pytest.ini
    │   ├── requirements.txt
    │   └── requirements-dev.txt    # + pytest, pour le développement/CI uniquement
    └── frontend/                    # HTML/CSS/JS statique, aucun framework
        ├── index.html
        ├── css/style.css
        ├── css/leaflet.css          # Vendorisé (carte GeoIP, voir 7.10.5)
        ├── js/app.js
        ├── js/vendor/leaflet.js     # Vendorisé
        └── data/sample-data.json    # Jeu de données de démo (mode hors-ligne, lecture seule)
```

---

## 4. Étape 1- Déploiement de l'infrastructure Azure (Terraform)

Fichiers concernés : `terraform/` (racine + modules `network` et `compute`)

L'infrastructure est organisée en **modules Terraform réutilisables**, pattern standard en entreprise pour industrialiser des LABs ou des environnements multiples (dev/staging/prod) à partir des mêmes briques :

- `modules/network` : VNet, sous-réseau, NSG et ses règles (SSH, WireGuard, dashboard, deny-all)
- `modules/compute` : IP publique, interface réseau, VM Ubuntu 22.04 LTS avec cloud-init

### 4.1 Personnaliser les variables

```bash
git clone https://github.com/dspitech/blockhash-wireguard-lab.git && cd blockhash-wireguard-lab/terraform && cp terraform.tfvars.example terraform.tfvars
```

<img width="1881" height="522" alt="image" src="https://github.com/user-attachments/assets/af50a882-71b6-4e0c-8831-c14575fab6bd" />

Éditez `terraform.tfvars` :

```hcl
admin_password   = "VotreMotDePasseFort!2026"  # Mot de passe de la VM
admin_source_ip  = "203.0.113.10/32"   # votre IP publique -> whatismyipaddress.com
dns_label_prefix = "blockhash-wg-lab"  # doit etre unique dans la region Azure
```

<img width="1731" height="656" alt="image" src="https://github.com/user-attachments/assets/2c87a7b5-5df8-4407-86c0-9d4aa9d7f066" />


> **Bonne pratique :** en environnement de production, ne laissez jamais `admin_source_ip` en `*`. Restreignez systématiquement l'accès SSH et au dashboard à votre IP (ou à une plage d'IP d'entreprise / un VPN d'administration). Préférez également `use_ssh_key = true` avec une clé publique plutôt qu'un mot de passe.

`terraform.tfvars` contient des secrets : ne le committez jamais dans un dépôt Git public (il est déjà exclu via `.gitignore`- voir section 15).

### 4.2 Lancer le déploiement

```bash
terraform fmt && terraform init && terraform validate && terraform plan && terraform apply -auto-approve
```

<img width="1923" height="750" alt="image" src="https://github.com/user-attachments/assets/d8414692-ab83-4c8d-9601-17f2fc25188d" />

<img width="791" height="287" alt="image" src="https://github.com/user-attachments/assets/e434bde9-f4ee-4c3c-87a8-783dfd3f04f4" />

<img width="1330" height="581" alt="image" src="https://github.com/user-attachments/assets/577d0639-18a8-423b-86f1-e801b8d571aa" />


Ou, sous Windows, via l'assistant fourni :

```powershell
cd terraform
./deploy.ps1
```

À la fin du déploiement, Terraform affiche les sorties utiles :

```bash
terraform output
# vm_public_ip, vm_fqdn, ssh_command, dashboard_url
```

### 4.3 Vérification

```bash
az vm show -g RG-Lab-WireGuard -n vm-wireguard-lab -d -o table
terraform state list
```

<img width="1507" height="220" alt="image" src="https://github.com/user-attachments/assets/46ff6640-6cc4-406c-8eec-4edae5a27ad3" />
<img width="1272" height="425" alt="image" src="https://github.com/user-attachments/assets/c95b3999-2cb3-4c65-b8af-f0e2b8dd97cf" />


### 4.4 Pourquoi des modules ?

Structurer l'infrastructure en modules (`network`, `compute`) plutôt qu'un fichier unique permet, en contexte professionnel, de :
- réutiliser le module `network` pour d'autres LABs (pentest, formation Kubernetes, etc.) ;
- faire évoluer la taille de VM ou la région sans toucher aux règles réseau ;
- versionner et tester chaque module indépendamment (`terraform validate` par module) ;
- préparer une future publication interne sur un **registre Terraform privé** de BLOCKHash.

---

## 5. Étape 2- Installation du serveur WireGuard

Fichier concerné : `scripts/01-install-wireguard-server.sh`

### 5.1 Connexion à la VM

```bash
ssh wgadmin@<FQDN_ou_IP_publique>
```
<img width="1115" height="495" alt="image" src="https://github.com/user-attachments/assets/0158a223-1c92-46f3-b4ea-4ad68d605428" />

### 5.2 Transfert et exécution du script

Depuis votre poste local :

```bash
git clone https://github.com/dspitech/blockhash-wireguard-lab.git && cd blockhash-wireguard-lab/scripts
```
<img width="1656" height="487" alt="image" src="https://github.com/user-attachments/assets/263e064a-65e3-41e3-8fbe-9350bfeee8af" />

Sur la VM :

```bash
chmod +x *.sh
sudo ./01-install-wireguard-server.sh
```

<img width="1584" height="402" alt="image" src="https://github.com/user-attachments/assets/9ac8ae0e-e982-421d-b20c-89ebea908748" />


### 5.3 Ce que fait le script

- Met à jour le système (`apt update && apt upgrade`)
- Installe `wireguard`, `wireguard-tools`, `qrencode`, `ufw`
- Active le routage IPv4 (`net.ipv4.ip_forward=1`)
- Génère la paire de clés du serveur (Curve25519)
- Crée `/etc/wireguard/wg0.conf` avec les règles NAT (`iptables MASQUERADE`)
- Ouvre le port UDP 51820 dans `ufw`
- Active et démarre le service `wg-quick@wg0`

### 5.4 Vérification

```bash
sudo systemctl status wg-quick@wg0
sudo wg show
ip a show wg0
```

Vous devez voir l'interface `wg0` active avec l'adresse `10.66.66.1/24` et la clé publique du serveur affichée.

<img width="1371" height="660" alt="image" src="https://github.com/user-attachments/assets/da7a9a1f-752b-454a-8789-929e71d4161f" />

<img width="1077" height="352" alt="image" src="https://github.com/user-attachments/assets/afa8c1b6-24d5-44b3-ae28-caf4ec38a201" />

<img width="1280" height="287" alt="image" src="https://github.com/user-attachments/assets/16f2eaa0-9a9e-452a-9c3b-ffbd0c74679f" />



---

## 6. Étape 3- Création et distribution des clients

Fichier concerné : `scripts/02-add-client.sh`

### 6.1 Ajouter un client

```bash
sudo ./02-add-client.sh ordinateur-alice
```

Le script :
- génère une paire de clés + une clé pré-partagée (PSK) pour ce client ;
- attribue automatiquement la prochaine IP libre du tunnel (`10.66.66.2`, `.3`, ...) ;
- ajoute le bloc `[Peer]` correspondant dans `wg0.conf` **sans redémarrer le service** (`wg syncconf`) ;
- génère le fichier `clients/ordinateur-alice.conf` prêt à l'emploi ;
- affiche un **QR code** dans le terminal (scannable directement depuis l'app mobile WireGuard).

<img width="1686" height="981" alt="image" src="https://github.com/user-attachments/assets/3bac56b1-3d42-447b-9939-b0589e512c0a" />

### 6.2 Distribuer la configuration

**Poste desktop (Windows/macOS/Linux) :**

1. **Installer l'application WireGuard sur Windows** — téléchargez l'installeur officiel sur [wireguard.com/install](https://www.wireguard.com/install/) (lien "Windows"), puis lancez-le. C'est un simple `.exe`, aucune configuration nécessaire à l'installation.
2. **Récupérer le fichier `.conf` généré sur le serveur** — ce fichier a déjà été créé par le script `02-add-client.sh` sur la VM (ex. `ordinateur-alice.conf`). Depuis Windows, ouvrez PowerShell (Windows 10/11 embarque `scp`) et tapez :
```powershell
   scp wgadmin@<FQDN>:/etc/wireguard/clients/ordinateur-alice.conf C:\Users\VotreNom\Desktop\
```
   — ou utilisez [WinSCP](https://winscp.net/) si vous préférez une interface graphique.
3. **Importer le fichier dans l'application WireGuard** — ouvrez WireGuard, cliquez sur **"Import tunnel(s) from file"**, puis sélectionnez le fichier `.conf` récupéré à l'étape précédente. Le tunnel apparaît automatiquement dans la liste à gauche : rien à créer ou configurer manuellement, l'import fait tout.
4. **Activer le tunnel** — sélectionnez le tunnel dans la liste et cliquez sur **"Activate"** (ou basculez l'interrupteur). La connexion VPN démarre immédiatement.
5. **Vérifier que ça fonctionne** — ouvrez un navigateur et allez sur [whatismyipaddress.com](https://whatismyipaddress.com), ou dans PowerShell tapez `curl ifconfig.me`. L'IP affichée doit être celle du serveur (Azure ou votre box), pas votre IP personnelle habituelle.

<img width="1435" height="987" alt="image" src="https://github.com/user-attachments/assets/8489a755-287c-458e-84dd-fe7fc71c70e1" />


### 6.3 Révoquer un client (optionnel)

```bash
sudo ./05-revoke-client.sh ordinateur-alice
```

Retire le peer à chaud (sans coupure de service) et archive ses clés dans `clients/revoked/`.

---

## 7. Étape 4- Dashboard de supervision BLOCKHash

Fichiers concernés : `dashboard/` (backend Flask + frontend HTML/CSS/JS), `scripts/03-install-dashboard.sh`

Ce LAB inclut un **dashboard**, conçu et maintenu par BLOCKHash- pas de dépendance à un outil tiers. Il affiche en temps réel :

- des **cartes indicateurs** (tunnels actifs, volume reçu/émis, alertes) et un graphique de débit en direct ;
- un **journal des connexions triable et filtrable** (clic sur chaque colonne, recherche libre, filtres par statut) alimenté par les logs CSV de l'étape 5 ;
- une **grille de clients** avec statut (en ligne / inactif / jamais connecté), dernier handshake et volumes de données ;
- un **mode démonstration** automatique : si l'API est injoignable, le dashboard bascule sur un jeu de données d'exemple (`dashboard/frontend/data/sample-data.json`)- utile pour présenter le produit à un client avant tout déploiement réel.

### 7.1 Architecture du dashboard

```
Navigateur ──HTTP──▶ gunicorn (Flask, /opt/blockhash-dashboard)
                        ├── GET /api/overview  → wg show wg0 dump + tunnels.csv
                        └── / (statique)        → index.html / style.css / app.js
```

Aucune base de données : l'API lit directement l'état WireGuard en direct (`wg show`) et le fichier de logs CSV généré par `04-logging-monitoring.sh`. C'est volontairement simple et sans dépendance lourde, adapté à un LAB comme à un petit déploiement de production.

### 7.2 Installation

Depuis la VM, dans le dossier `dashboard/` lancez le script d'installation :

```bash
cd ~/blockhash-wireguard-lab
ls dashboard          # doit lister backend/ et frontend/ 
sudo ./scripts/03-install-dashboard.sh 8080
```

Le script :
- installe Python 3, crée un environnement virtuel et installe Flask + gunicorn ;
- copie l'application dans `/opt/blockhash-dashboard` ;
- génère un jeton d'API (`/etc/blockhash/dashboard.env`) ;
- autorise le service à lire l'état WireGuard sans lui donner les droits root complets (`sudoers` restreint à `wg show`, ou capacité `CAP_NET_ADMIN`- voir le script) ;
- crée et démarre le service systemd `blockhash-dashboard` (gunicorn, 2 workers) ;
- ouvre le port choisi (8080 par défaut) dans `ufw`.

<img width="1740" height="982" alt="image" src="https://github.com/user-attachments/assets/78de9d13-bdc5-44ae-b824-e692bb488cb6" />

### 7.3 Accès au Dashboard

```
http://<FQDN_ou_IP_publique>:8080
```

> **Important :** le port du dashboard est déjà restreint à votre `admin_source_ip` au niveau du NSG Terraform (`modules/network`). Vérifiez également la règle `ufw` correspondante (`sudo ufw status`).

### 7.4 Personnalisation

- **Palette et identité visuelle** : `dashboard/frontend/css/style.css` (variables CSS en tête de fichier- couleurs, typographies) pour adapter aux couleurs d'un client si vous revendez ce LAB.
- **Fréquence de rafraîchissement** : `REFRESH_INTERVAL_MS` dans `dashboard/frontend/js/app.js` (30 secondes par défaut).
- **Seuil "en ligne"** : `HANDSHAKE_ONLINE_THRESHOLD_SEC` dans `dashboard/backend/app.py` (180 secondes par défaut).

### 7.5 Vérification et logs applicatifs

```bash
sudo systemctl status blockhash-dashboard
sudo journalctl -u blockhash-dashboard -f
curl -s http://localhost:8080/healthz
```

<img width="1911" height="877" alt="image" src="https://github.com/user-attachments/assets/dd8e91e8-b821-4531-94e5-91932ffdbaf0" />

### 7.6 Gestion des clients depuis le dashboard

Fichiers concernés : `dashboard/backend/wgctl.py` (logique privilégiée), `dashboard/backend/app.py` (endpoints `/api/clients/*`), `dashboard/frontend/js/app.js` (modales, tiroir d'historique), `scripts/06-manage-client.sh` et `scripts/07-check-expirations.sh` (équivalents CLI).

Au-delà de la supervision en lecture seule (section 7), le dashboard permet désormais de **gérer le cycle de vie complet des clients WireGuard sans passer par SSH** :

| Fonctionnalité | Où | Détail |
|---|---|---|
| Activer / désactiver un client | Carte client → bouton *Activer*/*Désactiver* | Retire ou remet le `[Peer]` en direct **sans supprimer** sa configuration (voir 7.6.2) |
| Révoquer définitivement | Carte client → *Révoquer* (confirmation requise) | Supprime le bloc `[Peer]`, archive les clés dans `clients/revoked/` |
| Ajouter un client | Bouton *Ajouter un client* (vue Clients) | Formulaire nom + expiration optionnelle → génère les clés, écrit dans `wg0.conf`, affiche le QR code et propose le `.conf` en téléchargement |
| Renommer un client | Carte client → *Renommer* | Met à jour le commentaire `# Client :` et renomme les fichiers `clients/<nom>.*` associés |
| Expiration automatique | Carte client → *Expiration* | Date au-delà de laquelle le client est **désactivé automatiquement** (cron quotidien, voir 7.6.4) |
| Limitation de bande passante | Carte client → *Bande passante* | Débit montant/descendant en Mb/s par pair (`tc`/HTB, voir 7.6.5 - fonctionnalité avancée, best effort) |
| Régénérer la config/QR | Carte client → *Régénérer* | Nouvelles clés + PSK pour un client existant (même nom, même IP) ; utile en cas de suspicion de compromission |
| Revoir la config/QR existants | Carte client → *QR / Config* | Réaffiche le `.conf` et le QR déjà générés, sans toucher aux clés |
| Historique par client | Carte client → *Historique* | Tiroir dédié : graphique de débit propre au client, dernière IP endpoint vue, nombre de reconnexions estimé (voir 7.6.5) |

#### 7.6.1 Sécurité : élévation des droits sudo

Les fonctionnalités ci-dessus **nécessitent d'élargir les droits sudo** de `www-data` (l'utilisateur sous lequel tourne gunicorn), qui n'avait jusque-là que le droit d'exécuter `wg show wg0 dump` (lecture seule, non destructif).

Plutôt que d'autoriser directement `wg set`, l'édition de `wg0.conf` ou `wg syncconf` en sudoers (ce qui reviendrait à donner à `www-data` un accès quasi-root à l'interface réseau), ce LAB introduit un **point d'entrée unique et privilégié** : `dashboard/backend/wgctl.py`.

```bash
$SERVICE_USER ALL=(root) NOPASSWD: /usr/bin/wg show wg0 dump
$SERVICE_USER ALL=(root) NOPASSWD: /usr/bin/python3 /opt/blockhash-dashboard/backend/wgctl.py *
```

Ce choix de conception limite le risque de plusieurs façons :

- **Surface d'attaque réduite** : `www-data` ne peut exécuter *que* les actions que `wgctl.py` expose (`add`, `enable`, `disable`, `rename`, `revoke`, `regenerate`, `set-expiry`, `set-bandwidth`, `check-expirations`, `list`), jamais une commande shell arbitraire.
- **Validation systématique** : chaque nom de client est vérifié par une expression régulière stricte (`[A-Za-z0-9_-]{1,32}`) avant toute écriture disque, ce qui empêche l'injection de commande ou l'écriture en dehors de `/etc/wireguard/`.
- **Fichier root:root, non inscriptible par www-data** : `03-install-dashboard.sh` verrouille `wgctl.py` en `root:root` / `chmod 750` **après** avoir donné la propriété du reste de l'application à `www-data`. C'est essentiel : si `www-data` pouvait modifier `wgctl.py`, la règle sudoers ci-dessus lui donnerait un accès root complet (élévation de privilèges triviale). Le script réapplique cette vérification une seconde fois en toute fin d'installation par sécurité.
- **Écriture atomique** : `wg0.conf` est toujours réécrit dans un fichier temporaire puis déplacé (`os.replace`), jamais modifié en place, pour éviter une configuration à moitié écrite en cas de coupure.
- **JSON uniquement sur stdout** : `wgctl.py` ne renvoie jamais de trace Python brute à l'appelant (donc au navigateur), afin de ne pas fuiter de détails d'implémentation en cas d'erreur.

**Si vous préférez garder le dashboard strictement en lecture seule** (recommandé pour un dashboard exposé plus largement, ou en environnement de démonstration public) :

```bash
# /etc/blockhash/dashboard.env
CLIENT_MANAGEMENT_ENABLED=false
```

puis `sudo systemctl restart blockhash-dashboard`. Le frontend détecte automatiquement ce mode et masque les actions de gestion (voir la bannière *"Gestion des clients indisponible"* dans la vue Clients). Vous pouvez alors soit retirer la règle sudoers `wgctl.py`, soit la laisser en place sans risque supplémentaire tant que le service ne l'utilise pas.

Comme toujours dans ce LAB : **ne déployez pas ces droits élargis sur un serveur exposé directement à Internet sans restreindre l'accès au dashboard** (NSG/`ufw` + jeton d'API, voir sections 7.3 et 11).

#### 7.6.2 Comment un client désactivé est représenté

`wgctl.py` ne supprime jamais un bloc `[Peer]` lors d'une désactivation : il préfixe chacune de ses lignes d'un `#` supplémentaire, ce qui le rend invisible pour `wg-quick strip` (donc pour `wg syncconf`) sans le retirer du fichier :

```conf
[Peer]
# Client : ordinateur-alice
# Meta : {"created":"2026-09-01T10:00:00+00:00","expires":null,"bw_up_mbit":null,"bw_down_mbit":null}
PublicKey = ...
PresharedKey = ...
AllowedIPs = 10.66.66.2/32
```

devient, une fois désactivé :

```conf
#[Peer]
## Client : ordinateur-alice
## Meta : {"created":"2026-09-01T10:00:00+00:00","expires":null,"bw_up_mbit":null,"bw_down_mbit":null}
#PublicKey = ...
#PresharedKey = ...
#AllowedIPs = 10.66.66.2/32
```

Réactiver le client retire ce préfixe et relance `wg syncconf` : le pair revient **avec les mêmes clés et la même IP**, sans que l'utilisateur final ait besoin de réimporter son fichier `.conf`.

#### 7.6.3 Utilisation en CLI (sans passer par le dashboard)

Toutes ces actions restent disponibles en SSH via `scripts/06-manage-client.sh`, une fine couche au-dessus de `wgctl.py` :

```bash
sudo ./06-manage-client.sh add ordinateur-alice 30      # + 30 jours avant expiration
sudo ./06-manage-client.sh disable ordinateur-alice
sudo ./06-manage-client.sh enable ordinateur-alice
sudo ./06-manage-client.sh rename ordinateur-alice pc-alice-rh
sudo ./06-manage-client.sh expiry pc-alice-rh 2026-12-31
sudo ./06-manage-client.sh bandwidth pc-alice-rh 20 50   # 20 Mb/s upload, 50 Mb/s download
sudo ./06-manage-client.sh regenerate pc-alice-rh
sudo ./06-manage-client.sh revoke pc-alice-rh
sudo ./06-manage-client.sh list
```

#### 7.6.4 Expiration automatique (cron)

`03-install-dashboard.sh` installe `/etc/cron.d/blockhash-expirations`, qui exécute chaque nuit à 3h :

```bash
python3 /opt/blockhash-dashboard/backend/wgctl.py check-expirations
```

Tout client dont la date d'expiration est dépassée est désactivé (au sens de 7.6.2, pas révoqué) et journalisé dans `/var/log/wireguard/expirations.log`. Vous pouvez lancer la même vérification manuellement avec `sudo ./scripts/07-check-expirations.sh`.

#### 7.6.5 Limites connues

- **Bande passante (`tc`/HTB)** : fonctionnalité *avancée* et *best effort*, explicitement signalée comme telle dans l'énoncé de ce TP. Elle nécessite le module noyau `ifb` et `iproute2` (installés par `03-install-dashboard.sh`). Selon le noyau/la distribution, certaines commandes `tc` peuvent échouer silencieusement côté noyau : le dashboard vous le signale (`tc_applied: false` dans la réponse API, toast d'erreur côté UI) plutôt que de prétendre que la limite est active alors qu'elle ne l'est pas. La limite "logique" (Mb/s enregistrés) est de toute façon conservée dans `wg0.conf` même si `tc` échoue, pour ne pas perdre l'intention si vous corrigez le problème plus tard.
- **Compteur de reconnexions** : le journal `tunnels.csv` est échantillonné toutes les 5 minutes (cron, voir section 8), pas événementiel. Le dashboard approxime les reconnexions en comptant les changements d'IP endpoint et les écarts de plus de 10 minutes entre deux captures consécutives- une heuristique raisonnable pour un LAB, pas un décompte exact au sens d'un pare-feu stateful.
- **Régénération de clés** : régénérer un client change ses clés WireGuard ; l'ancien fichier `.conf` distribué au client cesse immédiatement de fonctionner et **doit être réimporté** (nouveau QR code/`.conf` fourni par le dashboard).

### 7.7 Monitoring et alerting avancés

Fichiers concernés : `dashboard/backend/store.py` (métriques long terme + historique d'alertes, SQLite), `dashboard/backend/system_monitor.py` (CPU/RAM/disque/services), `dashboard/backend/anomalies.py` (détection simple), `dashboard/backend/alerts.py` (moteur de notification), `dashboard/backend/settings_store.py` (réglages ajustables à chaud), `dashboard/backend/wgstate.py` (logique de lecture partagée, voir 7.7.1), `scripts/09-check-alerts.sh` (cron), onglets **Monitoring** et **Alertes** du dashboard.

| Fonctionnalité | Où | Détail |
|---|---|---|
| Historique long terme du débit | Onglet Monitoring, sélecteur 1h/24h/7j/30j | Graphique dédié, alimenté par une petite base **SQLite** (pas le CSV) pour rester rapide même sur 30 jours |
| Alertes configurables | Onglet Alertes | Email (SMTP), Slack, Discord, Telegram - règles : inactivité prolongée, seuil de débit, service down |
| Seuil "en ligne" ajustable | Onglet Alertes → Réglages généraux | Remplace la constante `HANDSHAKE_ONLINE_THRESHOLD_SEC` figée en dur ; persistée dans un fichier JSON, prise en compte immédiatement (pas de redémarrage du service) |
| Monitoring du serveur hôte | Onglet Monitoring → Système hôte | CPU, RAM, disque, uptime (via `psutil`) |
| Détection d'anomalies simples | Onglet Monitoring → Anomalies détectées | Pic de trafic inhabituel (z-score sur le débit récent) ; endpoint qui change trop souvent (indice de clé compromise/partagée) |
| Statut des services systemd | Onglet Monitoring (Système hôte) et Alertes (règle "service down") | `wg-quick@wg0` et `blockhash-dashboard`, via `systemctl is-active` |

#### 7.7.1 Pourquoi une base SQLite en plus du CSV existant ?

Le CSV (`tunnels.csv`, section 8) reste la source du journal brut et de l'heuristique de reconnexion : le relire intégralement pour un graphique sur 30 jours (des milliers de lignes par client) serait lent et fragile. `store.py` ajoute donc une petite base SQLite (`/var/log/wireguard/blockhash.db`) alimentée par un hook ajouté au **même** script de capture 5 minutes (`wg-log-snapshot.sh`, voir section 8) : rien de nouveau à surveiller, juste une écriture supplémentaire à chaque cycle déjà existant.

**Point technique important** : les compteurs `rx_bytes`/`tx_bytes` renvoyés par `wg show` sont **cumulatifs depuis le démarrage de l'interface**, pas un débit instantané. `store.py` stocke les valeurs brutes puis calcule le **delta** entre deux échantillons consécutifs au moment de la requête (`store.query_series`), pour obtenir un vrai débit par intervalle. Le graphique historique de la vue Monitoring utilise cette méthode ; le petit graphique "Débit du tunnel" de la vue d'ensemble (Étape 4, section 7.3) reste basé sur le CSV et somme les compteurs bruts par fenêtre de 5 minutes - une simplification héritée, suffisante pour un coup d'œil rapide sur les 12 derniers points, mais moins rigoureuse que le nouveau graphique à sélecteur de plage.

Pour eviter toute duplication de logique de lecture entre le service web (`app.py`, sous Flask/gunicorn) et les scripts cron indépendants (`alerts.py`), la lecture de `wg0.conf` et de `wg show` a été extraite dans `wgstate.py`, un module **sans aucune dépendance externe** (bibliothèque standard uniquement) que les deux réutilisent.

#### 7.7.2 Détection d'anomalies : ce que ça fait (et ne fait pas)

- **Pic de trafic** : compare le dernier bucket de débit (fenêtre 24h) à la moyenne et à l'écart-type des buckets précédents ; signale si le dernier dépasse `moyenne + 3×écart-type` (et un plancher minimal pour ne pas signaler du bruit sur un tunnel presque silencieux).
- **Endpoint flapping** : réutilise l'heuristique de reconnexion déjà calculée pour l'historique par client (section 7.6) ; au-delà de 6 changements d'endpoint en 24h, le client est signalé - un indice possible de clé privée partagée entre plusieurs appareils, pas une certitude.

Ce n'est **pas** un IDS : pas de machine learning, pas de base de référence par client, pas de whitelisting d'IP. C'est volontairement simple et lisible, pour un contexte pédagogique - libre à vous de le remplacer par une vraie stack d'observabilité (Prometheus + Grafana + Alertmanager, par exemple) si ce LAB grandit.

#### 7.7.3 Sécurité de l'alerting

Contrairement à la gestion des clients (section 7.6.1), **l'alerting ne nécessite aucune extension des droits sudo**. `alerts.py` ne fait que :
- lire `wg0.conf` et `wg show wg0 dump` (déjà autorisé) ;
- lire/écrire son propre fichier de configuration sous `/etc/blockhash/alerts-config.json` (appartient à `www-data`, `chmod 600` - ce fichier contient des secrets : mot de passe SMTP, URLs de webhook, jeton de bot Telegram) ;
- effectuer des requêtes HTTP sortantes vers les webhooks/API de notification configurés.

**Masquage des secrets** : `GET /api/alerts/config` ne renvoie jamais un secret en clair - un champ déjà configuré est renvoyé sous la forme `••••••••`. Le formulaire du dashboard renvoie cette même valeur telle quelle si vous ne la modifiez pas (voir `alerts.py:save_config`), donc resauvegarder le formulaire sans toucher au mot de passe SMTP ne l'efface pas. Si vous consultez ce fichier directement sur le serveur (`sudo cat /etc/blockhash/alerts-config.json`), les secrets y sont en clair - c'est un fichier de configuration serveur, pas une couche de chiffrement.

**L'alerting est désactivé par défaut** (`enabled: false`) : aucune notification n'est envoyée tant que vous ne l'activez pas explicitement depuis l'onglet Alertes.

#### 7.7.4 Activation du cron d'évaluation des règles

`03-install-dashboard.sh` installe `/etc/cron.d/blockhash-alerts`, qui exécute toutes les 5 minutes :

```bash
python3 /opt/blockhash-dashboard/backend/alerts.py check
```

Chaque règle a son propre délai de répétition (`cooldowns_sec` dans la config) pour éviter le spam : par défaut, 1 alerte d'inactivité par client et par jour, 1 alerte de débit par client et par heure, 1 alerte de service down toutes les 30 minutes tant que le problème persiste. Vous pouvez déclencher une vérification manuelle avec `sudo python3 /opt/blockhash-dashboard/backend/alerts.py check`, ou tester un canal précis sans attendre une vraie condition d'alerte avec le bouton *Tester* de chaque canal dans le dashboard.

#### 7.7.6 Réinitialiser la déduplication (sans SSH)

Chaque règle qui s'est déclenchée reste "en pause" pendant son `cooldowns_sec` (voir 7.7.4) : c'est voulu, pour éviter qu'un client resté inactif ne déclenche une notification à chaque passage du cron. Mais en phase de test - par exemple pour vérifier qu'un webhook Slack fonctionne vraiment en conditions réelles - attendre le cooldown est peu pratique.

L'onglet **Alertes** affiche un panneau *Règles actuellement en pause (déduplication)* qui liste chaque règle en cooldown avec le temps écoulé depuis son dernier déclenchement, et permet de :
- **Réinitialiser** une règle précise (le bouton en face de chaque ligne) ;
- **Tout réinitialiser** (bouton en haut du panneau, avec confirmation).

Techniquement, cela vide (entièrement ou une seule ligne selon le cas) la table `alert_state` de `store.py`, via `GET/DELETE /api/alerts/dedup` et `DELETE /api/alerts/dedup/<rule_key>`. Cette table ne stocke que des horodatages de dédup - la vider ne supprime ni l'historique des alertes déjà envoyées (table `alerts`, affichée juste en dessous), ni la configuration des règles/canaux.

Pour les mêmes besoins en CLI (sans dashboard) :
```bash
python3 /opt/blockhash-dashboard/backend/store.py dedup-list
python3 /opt/blockhash-dashboard/backend/store.py dedup-clear --rule-key "inactive:<clé_publique_du_client>"
python3 /opt/blockhash-dashboard/backend/store.py dedup-clear   # sans --rule-key : reinitialise tout
```

#### 7.7.7 Limites connues

- **Détection d'anomalies** : heuristiques simples (voir 7.7.2), pas un système de détection d'intrusion.
- **Dédup des alertes** : si l'envoi d'une notification échoue (ex. webhook injoignable), la règle est quand même marquée comme "envoyée" pour la durée du cooldown - conçu pour un LAB, pas pour une garantie de livraison. Consultez `/var/log/wireguard/alerts.log` en cas de doute, ou réinitialisez la règle concernée depuis l'onglet Alertes (voir 7.7.6) une fois le problème corrigé.
- **`cpu_percent` au premier appel** : `psutil.cpu_percent()` a besoin d'un point de comparaison ; le tout premier appel après le démarrage du service renvoie `null` plutôt qu'un chiffre trompeur (`0.0`).

### 7.8 Administration système

Fichiers concernés : `dashboard/backend/wgops.py` (opérations privilégiées), `dashboard/backend/servers_store.py` (registre multi-serveurs), onglet **Système** du dashboard.

| Fonctionnalité | Où | Détail |
|---|---|---|
| Sauvegarde/restauration de `wg0.conf` | Onglet Système → *Sauvegardes* | Versionné sur disque (`/etc/wireguard/backups/`), avec **diff** avant application et sauvegarde de sécurité automatique avant toute restauration |
| Rotation assistée des clés serveur | Onglet Système → *Rotation des clés serveur* | Régénère la paire de clés du serveur **et** le `.conf` de chaque client existant (leurs propres clés ne changent pas) en une seule opération atomique |
| Redémarrage du tunnel | Onglet Système → *Maintenance du tunnel* | `systemctl restart wg-quick@wg0`, avec confirmation côté UI |
| Export d'audit | Onglet Système → *Export d'audit* | Zip de tous les `.conf` clients + `wg0.conf` + un manifeste CSV non sensible (nom, clé publique, IP, statut) |
| Multi-serveurs | Onglet Système → *Multi-serveurs* | Supervision agrégée de plusieurs instances BLOCKHash (voir 7.8.5) |

#### 7.8.1 Sécurité : un second point d'entrée privilégié

Comme pour la gestion des clients (section 7.6.1), ces opérations passent par un **point d'entrée unique et privilégié** : `dashboard/backend/wgops.py`, avec exactement les mêmes garanties que `wgctl.py` (root:root, `chmod 750`, validation stricte des paramètres, écriture atomique, jamais de trace Python brute renvoyée).

Ce module est volontairement **séparé** de `wgctl.py` plutôt que d'y ajouter des actions, et contrôlé par un interrupteur dédié `SYSTEM_OPS_ENABLED` (distinct de `CLIENT_MANAGEMENT_ENABLED`) : la rotation des clés serveur et le redémarrage du tunnel ont un rayon d'impact bien plus large qu'ajouter ou révoquer un client - un exploitant peut vouloir activer la gestion des clients depuis le web sans exposer ces opérations plus sensibles.

```bash
# /etc/blockhash/dashboard.env
SYSTEM_OPS_ENABLED=false   # masque ces actions sans toucher a CLIENT_MANAGEMENT_ENABLED
```

La règle sudoers ajoutée par `03-install-dashboard.sh` :
```bash
$SERVICE_USER ALL=(root) NOPASSWD: /usr/bin/python3 /opt/blockhash-dashboard/backend/wgops.py *
```

#### 7.8.2 Sauvegardes : ce qui est protégé

- Chaque sauvegarde est un fichier horodaté (`wg0_AAAAMMJJ-HHMMSS_<label>.conf`) sous `/etc/wireguard/backups/`, avec une rotation automatique (50 sauvegardes conservées par défaut, réglable via `WG_MAX_BACKUPS`).
- **Avant toute restauration**, une sauvegarde de l'état actuel est créée automatiquement (label `avant-restauration`) - une restauration malheureuse reste donc toujours réversible.
- Le **diff** (`diff-backup`) utilise `difflib` (bibliothèque standard Python) pour comparer une sauvegarde au `wg0.conf` actuel, ligne par ligne, avant de décider de restaurer.
- Les noms de fichiers de sauvegarde sont strictement validés côté serveur (regex + vérification que le chemin résolu reste dans le dossier des sauvegardes) pour empêcher tout traversal de chemin depuis l'API.

#### 7.8.3 Rotation des clés serveur : ce qui se passe exactement

1. Sauvegarde de sécurité de `wg0.conf` (label `avant-rotation-cles`).
2. Nouvelle paire de clés générée (`wg genkey` / `wg pubkey`).
3. `wg0.conf`, `server_private.key` et `server_public.key` mis à jour.
4. `wg syncconf` recharge l'interface à chaud, sans couper les tunnels déjà établis.
5. **Chaque** fichier `.conf` client sous `clients/*.conf` est réécrit : seule sa ligne `PublicKey` (celle qui pointe vers le **serveur**, dans le bloc `[Peer]` du fichier **client**) est remplacée par la nouvelle clé publique serveur. Les clés propres au client (sa `PrivateKey`, son `PresharedKey`, son IP) ne changent pas.
6. Le dashboard affiche la liste des clients concernés et rappelle qu'ils doivent réimporter leur configuration (nouveau `.conf`/QR à redistribuer, voir section 7.6 pour régénérer un client individuellement si besoin).

**Quand l'utiliser** : rotation périodique de routine (tous les 6-12 mois, voir section 11), ou en urgence si la clé privée du serveur est suspectée compromise.

#### 7.8.4 Export d'audit : contenu et sensibilité

Le zip généré contient :
- `clients/*.conf` — configuration complète de chaque client, **clé privée incluse** (rappel : ce LAB conserve les clés privées client côté serveur pour la simplicité, voir section 6) ;
- `wg0.conf` — configuration serveur complète (clé privée serveur incluse) ;
- `manifest.csv` — un résumé non sensible (nom, clé publique, IP, statut) pour un usage d'audit léger sans manipuler les clés privées.

**Ce zip est aussi sensible que l'ensemble de `/etc/wireguard/`** : à traiter avec les mêmes précautions (transfert chiffré, pas de stockage sur un partage non protégé). Les fichiers d'export sont écrits dans `/tmp/blockhash-exports/` et purgés automatiquement au bout d'une heure.

#### 7.8.5 Multi-serveurs : portée et limites

Le registre (`servers_store.py`) permet d'ajouter d'autres instances BLOCKHash (nom, URL, jeton d'API optionnel) et d'afficher un résumé agrégé (tunnels actifs, injoignabilité) sans quitter le dashboard courant. Techniquement :

- Le jeton d'API de chaque serveur distant est stocké côté serveur uniquement (`/etc/blockhash/servers.json`, `chmod 600`) et **jamais transmis au navigateur** - c'est le backend de *cette* instance qui interroge `/api/overview` du serveur distant pour le compte de l'utilisateur, puis relaie le résultat.
- **Ceci reste une supervision agrégée, pas une fédération complète** : gérer les clients, consulter le journal détaillé ou configurer les alertes d'un serveur distant se fait en ouvrant *son propre* dashboard (bouton *Ouvrir*), pas depuis cette instance. Étendre chaque vue (Clients, Journal, Monitoring...) pour qu'elle soit elle-même multi-serveur est un chantier plus large, volontairement hors scope de cette itération.
- Un serveur injoignable (mauvaise URL, jeton invalide, pare-feu) est signalé sans faire échouer le reste de la vue.

### 7.9 Reporting et export

Fichiers concernés : `dashboard/backend/reports.py`, onglets Journal (export), Alertes (rapport hebdomadaire) et Conformité.

| Fonctionnalité | Où | Détail |
|---|---|---|
| Export CSV du journal filtré | Onglet Journal → *Export CSV* | Reprend exactement les lignes actuellement affichées (filtre de statut + recherche + tri) |
| Export PDF du journal filtré | Onglet Journal → *Export PDF* | Même principe, rendu en PDF tabulaire côté serveur |
| Rapport hebdomadaire automatique | Onglet Alertes → *Rapport hebdomadaire par e-mail* | Résumé du trafic, des alertes et des clients inactifs, envoyé chaque lundi matin |
| Vue Conformité | Onglet Conformité | Clients actifs sans connexion depuis 7/15/30/60/90 jours (ou jamais connectés), exportable en CSV/PDF |

#### 7.9.1 Export CSV/PDF : cohérence avec ce qui est affiché

L'export CSV est généré **côté navigateur**, directement à partir des lignes déjà filtrées/triées visibles à l'écran (aucun appel serveur supplémentaire) : ce que vous exportez est exactement ce que vous voyez. L'export PDF envoie ces mêmes lignes déjà filtrées au serveur (`POST /api/reports/pdf`), qui les met en forme avec `fpdf2` (bibliothèque Python pure, aucune dépendance système comme `wkhtmltopdf` ou un navigateur headless).

Le même mécanisme (`build_table_pdf`, générique) est réutilisé pour l'export PDF de la vue Conformité - toute nouvelle vue tabulaire du dashboard peut s'en servir sans dupliquer de logique de mise en page.

#### 7.9.2 Vue Conformité : règle de classement

Un client **actif** (non désactivé) est listé s'il n'a pas de handshake depuis au moins 7 jours, ou s'il ne s'est **jamais** connecté. Chaque client est classé dans le plus grand seuil qu'il dépasse (90/60/30/15/7 jours), trié du plus inactif au moins inactif. Les actions *Désactiver*/*Révoquer* de cette vue appellent exactement les mêmes endpoints que l'onglet Clients (voir section 7.6) - la vue Conformité n'est qu'une présentation différente, filtrée, des mêmes données.

#### 7.9.3 Rapport hebdomadaire : configuration

Le rapport réutilise le **canal e-mail déjà configuré dans l'onglet Alertes** (section 7.7) - aucune configuration SMTP séparée. Deux champs propres au rapport :
- **Envoyer chaque lundi matin** (interrupteur, désactivé par défaut) ;
- **Destinataire** (optionnel - si vide, réutilise le destinataire e-mail déjà configuré pour les alertes).

Le contenu du rapport (`reports.build_weekly_summary`) : nombre de clients actifs, volume cumulé, nombre d'alertes déclenchées dans la semaine (détail inclus), et liste des clients inactifs depuis plus de 7 jours. Le bouton *Envoyer maintenant* déclenche un envoi immédiat, utile pour vérifier la mise en forme sans attendre lundi.

Le cron correspondant (`/etc/cron.d/blockhash-weekly-report`, installé par `03-install-dashboard.sh`) :
```bash
0 8 * * 1 root python3 /opt/blockhash-dashboard/backend/reports.py send-weekly
```
Il ne fait rien tant que l'interrupteur n'est pas activé - comme pour l'alerting (section 7.7.3), aucun envoi surprise après une simple installation.

#### 7.9.4 Limites connues

- **Export PDF** : mise en page volontairement simple (tableau + en-tête), pas un moteur de rapport avec graphiques intégrés - pour un besoin plus riche, générez le CSV et importez-le dans l'outil de reporting déjà utilisé par votre organisation.
- **Rapport hebdomadaire** : format texte brut (pas de mise en forme HTML), pour rester lisible sur n'importe quel client e-mail sans dépendance à un moteur de templates supplémentaire.
- **Vue Conformité** : se base sur le dernier handshake connu (`wg show`), pas sur un historique d'audit complet - un client désactivé puis réactivé repart avec un compteur d'inactivité à zéro dès sa prochaine connexion.

### 7.10 Temps réel, journal SQLite et fiabilité

Fichiers concernés : `dashboard/backend/store.py` (table `logs`), `dashboard/backend/geoip.py`, `dashboard/backend/tests/` (suite pytest), route `/api/events/stream` et `/healthz`/`/api/version` dans `app.py`.

#### 7.10.1 Le journal des connexions n'est plus lu depuis le CSV

Jusqu'ici, l'API relisait l'intégralité de `tunnels.csv` à chaque requête pour en extraire une page. Le journal est maintenant stocké dans la même base SQLite que les métriques long terme (table `logs` de `store.py`), avec pagination, filtrage et tri **au niveau SQL** (`LIMIT`/`OFFSET`/`WHERE`/`ORDER BY`) - l'API ne charge jamais plus que la page demandée en mémoire, quelle que soit la taille de l'historique.

Le fichier `tunnels.csv` continue d'être écrit par le même cron 5 minutes (`04-logging-monitoring.sh`) : ce n'est plus l'API qui le lit, mais il reste disponible comme trace texte brute (`grep`/`tail` sans outillage, export vers un autre système) - voir le commentaire en tête de ce script pour le détail.

`GET /api/logs` accepte désormais :
```
?limit=50&offset=0&search=<texte>&status=<online|idle|never>&sort_key=<timestamp|rx_bytes|tx_bytes|endpoint|allowed_ips>&sort_dir=<asc|desc>
```
et renvoie `{"total": N, "rows": [...]}`. Le filtre `status` (qui dépend de l'état **live** des pairs, pas d'une colonne de la table `logs`) est résolu côté serveur en une liste de clés publiques avant d'être combiné à la pagination SQL - un filtre de statut actif ne réduit donc jamais le nombre de lignes réellement disponibles par page, contrairement à un filtrage naïf après coup.

#### 7.10.2 Pagination côté interface

L'onglet Journal affiche désormais une vraie barre de pagination (taille de page 25/50/100/200, boutons Précédent/Suivant, compteur "X–Y sur Z"), remplaçant l'ancienne limite fixe de 100-200 entrées sans navigation. Les exports CSV/PDF (section 7.9.1) portent sur la page actuellement affichée.

#### 7.10.3 Temps réel : Server-Sent Events

`GET /api/events/stream` pousse trois types d'événements dès qu'ils se produisent, plutôt que d'attendre le prochain cycle de rafraîchissement (30 secondes) :
- `peer_connected` / `peer_disconnected` (changement de statut live d'un pair) ;
- `alert` (nouvelle ligne dans l'historique des alertes, section 7.7).

Le frontend s'y connecte via `EventSource` au chargement du dashboard et affiche un toast pour chaque événement. **Le rafraîchissement périodique de 30 secondes reste actif en parallèle** : si la connexion SSE échoue (proxy qui la bloque, navigateur ancien), le dashboard continue de fonctionner normalement, juste avec une latence de mise à jour plus longue - SSE est une amélioration de réactivité, pas une dépendance dure.

**Pourquoi pas de bus d'événements partagé entre workers ?** Chaque connexion SSE relit indépendamment l'état déjà partagé sur disque/dans le noyau (`wg show`, la table `alerts`) toutes les 3 secondes et ne pousse un événement que si quelque chose a changé depuis sa dernière lecture. Peu importe quel worker gunicorn traite quelle connexion : la source de vérité est le système de fichiers, pas une mémoire de process partagée - pas besoin de Redis ni d'une file de messages pour ce cas d'usage.

**Point d'attention deploiement**, déjà pris en compte par `03-install-dashboard.sh` : une connexion SSE reste ouverte plusieurs secondes. Avec des workers gunicorn "sync" par défaut, quelques onglets dashboard ouverts simultanément suffiraient à saturer tous les workers et bloquer le reste du trafic (y compris les fichiers statiques). Le service est donc configuré avec `--worker-class gthread --threads 4`, qui permet à chaque worker de gérer plusieurs connexions concurrentes via des threads, sans dépendance supplémentaire (contrairement à gevent/eventlet).

**Authentification SSE** : `EventSource` ne permet pas d'envoyer d'en-têtes personnalisés. Si `DASHBOARD_TOKEN` est configuré, le jeton est accepté en paramètre de requête (`?token=...`) **uniquement** pour cette route précise - un compromis documenté (un jeton en query string peut apparaître dans des logs d'accès), acceptable car l'accès au port du dashboard est déjà restreint au niveau réseau (section 7.3).

#### 7.10.4 Healthcheck complet et `/api/version`

`GET /healthz` ne se contente plus de vérifier que Flask répond : il vérifie aussi que `wg0.conf` est lisible, que `wg show` répond réellement, et que la base de métriques est accessible. Renvoie `503` (et le détail de chaque vérification) si l'un de ces points est en échec - utile derrière une sonde de supervision externe ou un load balancer, qui autrement verrait un service "up" alors que WireGuard lui-même est en panne.

`GET /api/version` renvoie la version du dashboard et l'état des interrupteurs de fonctionnalités (`client_management_enabled`, `system_ops_enabled`) - pratique pour un script d'inventaire ou de compatibilité.

Par ailleurs, un gestionnaire d'erreurs générique (`@app.errorhandler(Exception)`) garantit qu'**aucune** erreur inattendue ne renvoie une page d'erreur HTML Werkzeug ou une trace Python brute au client : toujours du JSON propre (`{"error": "..."}`), le détail complet restant dans les logs serveur (`journalctl -u blockhash-dashboard`) pour le diagnostic. C'est ce filet de sécurité qui a permis de détecter, pendant le développement, un cas réel où `sudo` absent du système faisait remonter une erreur 500 brute plutôt qu'un message clair - corrigé pour renvoyer une erreur 502 explicite.

#### 7.10.5 Carte des endpoints clients (GeoIP)

L'onglet Monitoring affiche une carte (Leaflet + fond de carte OpenStreetMap) plaçant chaque client connecté selon la géolocalisation approximative de son IP publique d'endpoint.

- Résolution via l'API gratuite [ip-api.com](https://ip-api.com/docs) (pas de clé requise, 45 requêtes/minute en usage non commercial), en un seul appel groupé (`/batch`) pour toutes les IP à résoudre.
- **Mise en cache** dans la base SQLite (table `geoip_cache`, 7 jours par défaut, réglable via `GEOIP_TTL_SEC`) : une même IP n'est réinterrogée qu'une fois la semaine passée, très loin de la limite de 45 requêtes/minute même avec de nombreux clients.
- Les IP privées/réservées (RFC1918, loopback, lien-local) ne sont **jamais** envoyées à l'API externe - elles ne peuvent de toute façon pas être géolocalisées et sont simplement absentes de la carte.
- Nécessite un accès Internet sortant depuis le serveur vers `ip-api.com` (HTTP) et `tile.openstreetmap.org` (HTTPS, chargé directement par le navigateur de l'utilisateur, pas par le serveur) - à vérifier si votre pare-feu sortant est restrictif.
- Best effort : si l'API GeoIP est injoignable, la carte s'affiche quand même (fond de carte vide de marqueurs) plutôt que de faire échouer tout l'onglet Monitoring.

#### 7.10.6 Tests automatisés

Une suite pytest (`dashboard/backend/tests/`) couvre la logique la plus sensible aux régressions silencieuses :
- `wgstate.py` : parsing des blocs `[Peer]` (actifs/désactivés), fusion avec `wg show`, heuristique de reconnexion ;
- `store.py` : calcul de **delta** (pas la somme brute des compteurs cumulatifs - la régression la plus facile à réintroduire par erreur), pagination/filtrage du journal, dédup des alertes ;
- `alerts.py` : masquage des secrets, fusion de config, évaluation des règles avec dédup ;
- `app.py` : forme des réponses API, codes d'erreur (403 quand une fonctionnalité est désactivée, 422 sur un nom de client invalide), combinaison filtre de statut + pagination.

Chaque test tourne dans un environnement **entièrement isolé** (répertoire temporaire, faux binaire `wg`, variables d'environnement dédiées via la fixture `wg_env`) - aucun test ne touche jamais `/etc/wireguard` ou `/etc/blockhash` du système réel.

```bash
cd dashboard/backend
pip install -r requirements-dev.txt --break-system-packages
pytest                      # toute la suite
pytest tests/test_store.py -v   # un seul fichier, verbeux
```

`requirements-dev.txt` est volontairement séparé de `requirements.txt` : pytest n'a aucune raison d'être installé sur le serveur de production, seulement dans un environnement de développement/CI.

### 7.11 Interface utilisateur avancée

Fichiers concernés : `dashboard/frontend/css/style.css` (variables de thème), `dashboard/frontend/js/app.js`, `dashboard/frontend/js/vendor/leaflet.js`.

| Fonctionnalité | Détail |
|---|---|
| Thème clair/sombre | Bouton dans la barre supérieure ; préférence mémorisée (`localStorage`) et réappliquée au prochain chargement |
| Recherche globale | Barre unique dans la barre supérieure, cherche simultanément dans les clients (déjà chargés) et le journal (requête `/api/logs?search=` limitée à 5 résultats) ; un clic sur un résultat bascule vers la bonne vue et applique le filtre correspondant |
| Mode NOC / plein écran | Masque la barre latérale, agrandit les chiffres clés, demande le plein écran navigateur - pensé pour un affichage continu sur un écran de salle |
| Chargement avec squelettes | Les cartes chiffrées affichent un effet de scintillement pendant le tout premier chargement, plutôt qu'un simple "–" statique |
| Menu mobile en tiroir | En dessous de 720px de large, la barre latérale devient un tiroir (bouton hamburger, fond assombri, fermeture automatique après un clic de navigation) plutôt qu'une barre horizontale à défilement - voir 7.11.1 |

#### 7.11.1 Un vrai bug mobile trouvé par le test visuel

Avec l'ajout progressif des onglets Conformité et Système, la barre latérale mobile (jusque-là transformée en barre horizontale défilante) ne pouvait plus afficher que 2 des 7 éléments de navigation, sans indice visuel qu'il y avait plus d'options en faisant défiler. Un test dans un vrai navigateur (Chromium headless, capture d'écran à 375px de large) l'a révélé immédiatement - remplacé par un tiroir de navigation classique (voir tableau ci-dessus), un motif d'interface mobile bien plus robuste face à l'ajout futur d'onglets.

#### 7.11.2 Limites connues

- **Recherche globale** : cherche les clients par nom/IP/endpoint et le journal par endpoint/IP/clé publique ; ne cherche pas (encore) dans l'historique des alertes ni les sauvegardes.
- **Mode NOC** : le plein écran navigateur peut être refusé silencieusement dans certains contextes (ex. iframe) - l'effet visuel (barre latérale masquée, textes agrandis) reste appliqué même si le vrai plein écran système échoue.
- **Thème clair** : conçu par inversion des mêmes variables CSS que le thème sombre ; les graphiques Chart.js/Leaflet gardent des couleurs adaptées automatiquement, mais un futur composant qui coderait une couleur en dur (plutôt que via une variable CSS) casserait le thème clair pour ce composant seulement.

---

## 8. Étape 5- Journalisation et logs

Fichier concerné : `scripts/04-logging-monitoring.sh`

### 8.1 Installation

```bash
sudo ./04-logging-monitoring.sh
```

Met en place :

| Composant | Détail |
|---|---|
| `/var/log/wireguard/tunnels.csv` | Capture toutes les 5 min (cron) : horodatage, clé publique du peer, endpoint, IP allouée, dernier handshake, octets reçus/envoyés |
| `logrotate` (`/etc/logrotate.d/wireguard`) | Rotation hebdomadaire, 12 semaines conservées, compression |
| Logs systemd | `journalctl -u wg-quick@wg0` pour les événements du service |

### 8.2 Consulter les logs

```bash
# Etat en temps reel
sudo wg show

# Historique CSV formate
column -s, -t < /var/log/wireguard/tunnels.csv | less

# Logs systemd en direct
sudo journalctl -u wg-quick@wg0 -f

# Export pour analyse (Excel, Power BI, ELK...)
cat /var/log/wireguard/tunnels.csv
```
<img width="1917" height="705" alt="image" src="https://github.com/user-attachments/assets/b5e420b4-ac98-42a3-bc13-8477cf251a48" />

<img width="1907" height="986" alt="image" src="https://github.com/user-attachments/assets/57461f0b-4def-40df-8490-d7fb470725ba" />

<img width="1897" height="867" alt="image" src="https://github.com/user-attachments/assets/96e8bc6e-d948-41cd-a160-0643244e2b28" />

<img width="1917" height="877" alt="image" src="https://github.com/user-attachments/assets/abeefa5d-1343-4638-b706-c4ab415515dd" />

Ces logs permettent, dans un cadre professionnel, de répondre à des besoins d'**audit** (qui s'est connecté, quand, combien de données échangées) et peuvent être ingérés par un SIEM ou un outil de supervision (ELK, Grafana + Loki, Azure Monitor via l'agent Log Analytics).

---

## 9. Étape 6- Tests et validation du tunnel

### 9.1 Depuis le serveur

```bash
sudo wg show wg0
# Doit lister chaque peer avec son "latest handshake"
```

### 9.2 Depuis le client

Après activation du tunnel dans l'application WireGuard :

```bash
# Verifier l'IP attribuee par le tunnel
ip a show wg0        # Linux
# ou ifconfig utun... # macOS

# Verifier que le trafic sort bien par le serveur Azure
curl ifconfig.me
# Doit renvoyer l'IP publique de la VM Azure, pas votre IP personnelle

# Tester la latence vers le serveur
ping 10.66.66.1

# Tracer le chemin reseau
traceroute 8.8.8.8
```

### 9.3 Test de bande passante (optionnel)

```bash
# Sur le serveur
sudo apt install -y iperf3
iperf3 -s

# Sur le client
iperf3 -c 10.66.66.1
```

---

## 10. Commandes Linux de référence

| Commande | Usage |
|---|---|
| `wg show` | Affiche l'état de toutes les interfaces WireGuard actives |
| `wg show wg0 dump` | Sortie machine-readable (utilisée par le script de logging) |
| `wg genkey` | Génère une clé privée |
| `wg pubkey < priv.key` | Dérive la clé publique |
| `wg genpsk` | Génère une clé pré-partagée (PSK) |
| `wg set wg0 peer <pubkey> remove` | Retire un peer à chaud |
| `wg syncconf wg0 <(wg-quick strip wg0)` | Recharge la config sans couper le tunnel |
| `sudo systemctl start\|stop\|restart wg-quick@wg0` | Contrôle du service |
| `sudo systemctl enable wg-quick@wg0` | Démarrage automatique au boot |
| `sudo ufw allow 51820/udp` | Ouvre le port WireGuard dans le pare-feu local |
| `sudo ufw status verbose` | Liste les règles de pare-feu actives |
| `sudo iptables -t nat -L -n -v` | Vérifie les règles NAT (MASQUERADE) |
| `sudo journalctl -u wg-quick@wg0 -f` | Suit les logs du service en direct |
| `ip a show wg0` | Affiche l'adresse IP de l'interface tunnel |
| `sysctl net.ipv4.ip_forward` | Vérifie que le routage IP est actif |
| `sudo systemctl status blockhash-dashboard` | État du dashboard (gunicorn) |
| `sudo journalctl -u blockhash-dashboard -f` | Suit les logs applicatifs du dashboard en direct |
| `curl -s http://localhost:8080/api/overview \| jq` | Interroge l'API du dashboard localement (formatage JSON) |
| `sudo ./scripts/06-manage-client.sh list` | Liste tous les clients (actifs et désactivés) avec leurs métadonnées |
| `sudo ./scripts/06-manage-client.sh add <nom> [jours]` | Ajoute un client (équivalent CLI de "Ajouter un client" dans le dashboard) |
| `sudo ./scripts/06-manage-client.sh disable\|enable <nom>` | Désactive/réactive un client sans le supprimer |
| `sudo ./scripts/07-check-expirations.sh` | Force la vérification des expirations (normalement en cron, voir 7.6.4) |
| `sudo tc -s qdisc show dev wg0` | Vérifie les classes/limites de débit actuellement appliquées par `tc` |
| `sudo visudo -cf /etc/sudoers.d/blockhash-dashboard` | Valide la syntaxe de la règle sudoers avant de la recharger |
| `python3 /opt/blockhash-dashboard/backend/store.py series --range 24h` | Affiche la série de débit agrégée (debug, sans passer par l'API) |
| `sudo python3 /opt/blockhash-dashboard/backend/alerts.py check` | Force une évaluation immédiate des règles d'alerte (hors cron) |
| `sudo python3 /opt/blockhash-dashboard/backend/alerts.py test slack` | Envoie une notification de test sur un canal (email/slack/discord/telegram) |
| `python3 /opt/blockhash-dashboard/backend/store.py dedup-list` | Liste les règles d'alerte actuellement en cooldown (voir 7.7.6) |
| `python3 /opt/blockhash-dashboard/backend/store.py dedup-clear --rule-key "..."` | Réinitialise le cooldown d'une règle précise (ou de toutes, sans `--rule-key`) |
| `sudo journalctl -u wg-quick@wg0 -f` puis `systemctl is-active wg-quick@wg0` | Vérifie l'état du service surveillé par la règle d'alerte "service down" |
| `sudo python3 /opt/blockhash-dashboard/backend/wgops.py list-backups` | Liste les sauvegardes de `wg0.conf` (debug, sans passer par l'API) |
| `sudo python3 /opt/blockhash-dashboard/backend/wgops.py backup --label pre-maintenance` | Crée une sauvegarde manuelle en CLI |
| `python3 /opt/blockhash-dashboard/backend/reports.py preview-weekly` | Affiche le contenu du rapport hebdomadaire sans l'envoyer |
| `sudo visudo -cf /etc/sudoers.d/blockhash-dashboard` | Valide la syntaxe de la règle sudoers (wgctl.py **et** wgops.py) avant de la recharger |
| `python3 /opt/blockhash-dashboard/backend/store.py logs --limit 20 --search 51820` | Interroge le journal SQLite directement (debug, sans passer par l'API) |
| `curl -sN http://localhost:8080/api/events/stream` | Suit le flux d'événements temps réel en direct dans le terminal |
| `curl -s http://localhost:8080/healthz \| jq` | Vérifie l'état détaillé du service (wg show, base de métriques) |
| `cd dashboard/backend && pytest` | Exécute la suite de tests automatisés (voir 7.10.6) |

---

## 11. Durcissement et bonnes pratiques de sécurité

- **Restreindre les sources** : ne jamais laisser `adminSourceIp` en `*` en production ; limiter le SSH et le dashboard à des IP nommées ou à un VPN d'administration dédié.
- **Rotation des clés** : régénérer les clés serveur/clients périodiquement (tous les 6-12 mois ou en cas de suspicion de compromission) - le bouton *Régénérer* du dashboard (ou `06-manage-client.sh regenerate`) automatise cette rotation pour un client donné.
- **PSK (clé pré-partagée)** : toujours l'utiliser en complément des clés Curve25519 (résistance additionnelle post-quantique partielle)- déjà activé par défaut dans `02-add-client.sh` et dans `wgctl.py`.
- **Authentification SSH par clé** : désactiver l'authentification par mot de passe une fois la VM opérationnelle (`PasswordAuthentication no` dans `/etc/ssh/sshd_config`).
- **Mise à jour automatique** : activer `unattended-upgrades` sur la VM.
- **Principe du moindre privilège** : un compte administrateur dédié par technicien, pas de partage de clé SSH.
- **Sauvegarde** : sauvegarder `/etc/wireguard/` (hors clés privées client si politique stricte) et l'exporter vers un coffre-fort de secrets (Azure Key Vault).
- **Surveillance** : envisager l'envoi des logs CSV vers Azure Monitor / Log Analytics pour alerting (ex. handshake absent depuis > 24h sur un peer critique).
- **Élévation sudo du dashboard (`wgctl.py`)** : voir la discussion dédiée en section 7.6.1. Points clés à ne pas oublier lors d'un durcissement ultérieur :
  - vérifier périodiquement que `dashboard/backend/wgctl.py` appartient bien à `root:root` (`ls -l /opt/blockhash-dashboard/backend/wgctl.py` doit afficher `-rwxr-x---` `root root`) ;
  - si vous n'avez pas besoin de la gestion des clients depuis le web, repassez `CLIENT_MANAGEMENT_ENABLED=false` dans `/etc/blockhash/dashboard.env` et retirez la ligne `wgctl.py` de `/etc/sudoers.d/blockhash-dashboard` ;
  - surveillez `/var/log/wireguard/expirations.log` et les logs `journalctl -u blockhash-dashboard` pour repérer un usage anormal (rafale de créations/révocations de clients, par exemple).
- **Secrets d'alerting (`/etc/blockhash/alerts-config.json`)** : contient en clair le mot de passe SMTP, les URLs de webhook Slack/Discord et le jeton de bot Telegram si vous les configurez. Le fichier est `chmod 600` et appartient à `www-data` (voir 7.7.3) - ne l'ajoutez jamais à un dépôt Git ni à une sauvegarde non chiffrée sans le traiter comme un secret.
- **Opérations système (`wgops.py`)** : mêmes précautions que pour `wgctl.py` (`root:root`, `chmod 750`, vérification périodique). Le rayon d'impact d'une compromission de `www-data` est ici plus large (redémarrage du service, rotation de clés) - envisagez de désactiver `SYSTEM_OPS_ENABLED` sur les déploiements où seule la lecture seule/la gestion des clients est nécessaire (voir 7.8.1).
- **Registre multi-serveurs (`/etc/blockhash/servers.json`)** : contient les jetons d'API d'autres instances BLOCKHash en clair. Traitez-le comme un secret au même titre que `alerts-config.json` ; si un serveur distant n'a plus besoin d'être supervisé, retirez-le du registre plutôt que de laisser un jeton inutilisé trainer.

---

## 12. Dépannage (Troubleshooting)

| Symptôme | Cause probable | Solution |
|---|---|---|
| Le tunnel ne se connecte pas | Port UDP 51820 fermé | Vérifier NSG Azure + `ufw status` |
| Connecté mais pas d'accès Internet | `ip_forward` désactivé ou règle NAT absente | `sysctl net.ipv4.ip_forward` doit renvoyer `1` ; vérifier `iptables -t nat -L` |
| "Handshake did not complete" | Horloge système désynchronisée, clé publique erronée | `timedatectl` ; vérifier la correspondance des clés client/serveur |
| Dashboard inaccessible | Port 8080 fermé ou service arrêté | `sudo systemctl status blockhash-dashboard` ; vérifier NSG/ufw |
| Dashboard affiche "Mode démonstration" en continu | L'API `/api/overview` ne répond pas (service arrêté, permissions `wg show`) | `sudo journalctl -u blockhash-dashboard -f` ; vérifier `/etc/sudoers.d/blockhash-dashboard` |
| Journal vide dans le dashboard alors que `wg show` fonctionne | Le script `04-logging-monitoring.sh` n'a pas encore tourné | Vérifier `/var/log/wireguard/tunnels.csv` et la tâche cron (`crontab -l`) |
| Bannière "Gestion des clients indisponible" dans la vue Clients | `CLIENT_MANAGEMENT_ENABLED=false`, mode démonstration, ou règle sudoers `wgctl.py` absente | Vérifier `/etc/blockhash/dashboard.env` puis `sudo -u www-data sudo -n python3 /opt/blockhash-dashboard/backend/wgctl.py list` |
| Erreur "Réponse invalide de wgctl.py" côté dashboard | Règle sudoers manquante/mal formée, ou `wgctl.py` non exécutable | `sudo visudo -cf /etc/sudoers.d/blockhash-dashboard` ; vérifier les permissions (`root:root`, `750`) sur `wgctl.py` |
| Limite de bande passante enregistrée mais sans effet réel | `tc`/`ifb` a échoué côté noyau (`tc_applied: false`) | `sudo tc -s qdisc show dev wg0` ; vérifier que le module `ifb` est chargé (`lsmod \| grep ifb`) et que `iproute2` est installé |
| Un client réactivé garde le statut "Jamais connecté" | Normal juste après la réactivation : `wg show` n'a pas encore vu de nouveau handshake | Attendre la prochaine tentative de connexion du client, ou forcer une reconnexion côté client |
| Le graphique "historique long terme" (onglet Monitoring) reste vide | Le cron de capture (`04-logging-monitoring.sh`) n'a pas encore tourné 5 minutes, ou `store.py` absent (dashboard pas encore installé au moment de l'installation du logging) | Attendre le prochain cycle cron ; vérifier `python3 /opt/blockhash-dashboard/backend/store.py series --range 1h` |
| Aucune alerte n'est jamais envoyée alors qu'une condition est clairement remplie | Alerting désactivé (`enabled: false` par défaut), ou canal non configuré | Activer l'interrupteur dans l'onglet Alertes ; vérifier `/var/log/wireguard/alerts.log` pour voir si le cron tourne |
| Une alerte ne se redéclenche jamais après une résolution puis une nouvelle occurrence | Cooldown de dédup pas encore écoulé (voir `cooldowns_sec` dans la config, 7.7.4) | Onglet Alertes → *Règles actuellement en pause* → *Réinitialiser* (ou *Tout réinitialiser*) - voir 7.7.6. Passer par `sqlite3` en SSH n'est plus nécessaire |
| `psutil non installé côté serveur` dans l'onglet Monitoring | `pip install -r requirements.txt` n'a pas installé `psutil` (échec de compilation, dépendances manquantes) | Vérifier `sudo $APP_DIR/venv/bin/pip show psutil` ; `apt install python3-dev gcc` puis réinstaller si besoin |
| Test d'un canal d'alerte échoue avec une erreur réseau | Webhook/API bloqué par le pare-feu sortant, ou identifiants invalides | Vérifier la connectivité sortante de la VM (`curl -I <url_webhook>`) et les identifiants saisis |
| Onglet Système affiche "opérations système désactivées" | `SYSTEM_OPS_ENABLED=false`, ou règle sudoers `wgops.py` absente | Vérifier `/etc/blockhash/dashboard.env` puis `sudo -u www-data sudo -n python3 /opt/blockhash-dashboard/backend/wgops.py list-backups` |
| Rotation des clés échoue avec "Section [Interface] sans PrivateKey" | `wg0.conf` a été édité manuellement et ne suit plus le format attendu | Restaurer une sauvegarde connue (onglet Système) avant de relancer la rotation |
| Après une rotation de clés, un client ne se reconnecte plus | Son `.conf` n'a pas été réimporté (nouvelle clé publique serveur) | Redistribuer le `.conf`/QR à jour depuis l'onglet Clients → *QR / Config* |
| Export d'audit ou export PDF renvoie une erreur 502/500 | `fpdf2` non installé dans le venv, ou espace disque insuffisant sous `/tmp` | `sudo $APP_DIR/venv/bin/pip show fpdf2` ; vérifier `df -h /tmp` |
| Rapport hebdomadaire jamais reçu bien qu'activé | Aucun serveur SMTP configuré dans l'onglet Alertes (le rapport réutilise ce canal) | Configurer et tester le canal e-mail dans Alertes, puis *Envoyer maintenant* depuis le rapport hebdomadaire |
| Un serveur distant apparaît "injoignable" dans Multi-serveurs | URL incorrecte, jeton invalide, pare-feu entre les deux VM | Vérifier l'URL/le jeton, tester `curl -H "X-API-Token: ..." <url>/api/overview` depuis le serveur courant |
| `/healthz` renvoie 503 | Un des sous-systèmes vérifiés est en panne (`wg show` ne répond pas, `wg0.conf` illisible, base de métriques inaccessible) | Regarder le détail dans `checks` de la réponse JSON pour cibler le bon sous-système |
| Aucune notification de toast en temps réel, tout passe par le rafraîchissement 30s | Connexion SSE bloquée (proxy, ancien navigateur) ou pas assez de threads gunicorn | Vérifier `curl -sN http://localhost:8080/api/events/stream` ; vérifier que le service tourne bien avec `--worker-class gthread` (voir 7.10.3) |
| Le dashboard répond très lentement dès que 2-3 onglets sont ouverts | Workers gunicorn saturés par des connexions SSE si `--worker-class gthread --threads` n'a pas été appliqué (mise à jour depuis une version antérieure) | Vérifier `systemctl cat blockhash-dashboard \| grep ExecStart`, réappliquer 03-install-dashboard.sh si besoin |
| La carte des endpoints clients reste vide | Pas d'accès Internet sortant vers `ip-api.com`/`tile.openstreetmap.org`, ou tous les endpoints sont des IP privées | Tester `curl http://ip-api.com/json` depuis le serveur ; la carte reste vide par conception pour des endpoints privés (LAN, VPN imbriqué) |
| Le menu mobile (hamburger) ne s'ouvre pas | JavaScript bloqué, ou largeur d'écran juste au-dessus du seuil de 720px | Vérifier la console navigateur ; le seuil est réglable dans `style.css` (`@media (max-width: 720px)`) |
| IP dupliquée entre deux clients | Attribution manuelle en doublon | Toujours utiliser `02-add-client.sh` pour l'auto-incrémentation |
| Logs vides dans `tunnels.csv` | Tâche cron non enregistrée | `crontab -l` / vérifier `/etc/crontab` ; relancer `04-logging-monitoring.sh` |

---

## 13. Nettoyage / destruction du LAB

Pour éviter toute facturation Azure inutile après le TP :

```bash
cd terraform && terraform destroy -auto-approve
```

<img width="906" height="127" alt="image" src="https://github.com/user-attachments/assets/7036fa90-b3f4-4b06-bb15-4da914d0fa24" />


Cette commande supprime l'intégralité des ressources (VM, disques, IP publique, NSG, VNet) gérées par l'état Terraform. Confirmez avec `yes` lorsque demandé.

---

## 14. Annexe- Exercices pour les stagiaires

1. Déployer l'infrastructure Azure avec un `vm_size` différent (`Standard_B1s`) via `terraform.tfvars` et mesurer l'impact sur les performances (`iperf3`).
2. Créer 3 clients WireGuard et documenter, pour chacun, l'IP attribuée et la clé publique.
3. Simuler une clé compromise : révoquer un client puis vérifier dans le dashboard que le peer a bien disparu.
4. Modifier `wireguard_client_source_ip` dans `terraform.tfvars` pour restreindre l'accès WireGuard à une seule IP source, exécuter `terraform apply`, et constater l'effet côté client.
7. Modifier la palette de couleurs du dashboard (`dashboard/frontend/css/style.css`) pour l'adapter à l'identité visuelle d'un client fictif, sans toucher au backend.
5. Exporter le fichier `tunnels.csv` d'une session de 30 minutes et produire un petit rapport (tableur) du volume de données par client.
6. (Avancé) Remplacer le split-tunneling par un tunnel complet (`AllowedIPs = 0.0.0.0/0`, déjà en place) puis basculer en split-tunneling (`AllowedIPs = 10.66.66.0/24`) et comparer le comportement.

---

## 15. Licence et conditions de diffusion

Ce LAB a été conçu par **BLOCKHash** comme support de formation professionnel.

- Les scripts et templates (`azure/`, `scripts/`) peuvent être adaptés librement pour un usage interne en entreprise.
- Toute redistribution commerciale de ce support (revente du LAB en tant que produit de formation) doit conserver la mention **« Développé par BLOCKHash »** dans ce README, sauf accord contraire écrit avec BLOCKHash.
- Ce support est fourni à titre pédagogique. BLOCKHash ne saurait être tenu responsable d'une mauvaise configuration réseau menant à une exposition non désirée d'un système en production- se référer systématiquement à la section 11 (Durcissement) avant tout déploiement réel.

---

**BLOCKHash**- Formation & Cybersécurité
