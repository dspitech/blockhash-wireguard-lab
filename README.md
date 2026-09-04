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
- Un **dashboard web maison** (HTML/CSS/JS + API Flask) de supervision des tunnels, avec journal triable/filtrable
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
│   └── 05-revoke-client.sh
└── dashboard/                      # Dashboard web maison
    ├── backend/                    # API Flask (lit wg show + tunnels.csv)
    │   ├── app.py
    │   └── requirements.txt
    └── frontend/                    # HTML/CSS/JS statique, aucun framework
        ├── index.html
        ├── css/style.css
        ├── js/app.js
        └── data/sample-data.json    # Jeu de données de démo (mode hors-ligne)
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

---

## 11. Durcissement et bonnes pratiques de sécurité

- **Restreindre les sources** : ne jamais laisser `adminSourceIp` en `*` en production ; limiter le SSH et le dashboard à des IP nommées ou à un VPN d'administration dédié.
- **Rotation des clés** : régénérer les clés serveur/clients périodiquement (tous les 6-12 mois ou en cas de suspicion de compromission).
- **PSK (clé pré-partagée)** : toujours l'utiliser en complément des clés Curve25519 (résistance additionnelle post-quantique partielle)- déjà activé par défaut dans `02-add-client.sh`.
- **Authentification SSH par clé** : désactiver l'authentification par mot de passe une fois la VM opérationnelle (`PasswordAuthentication no` dans `/etc/ssh/sshd_config`).
- **Mise à jour automatique** : activer `unattended-upgrades` sur la VM.
- **Principe du moindre privilège** : un compte administrateur dédié par technicien, pas de partage de clé SSH.
- **Sauvegarde** : sauvegarder `/etc/wireguard/` (hors clés privées client si politique stricte) et l'exporter vers un coffre-fort de secrets (Azure Key Vault).
- **Surveillance** : envisager l'envoi des logs CSV vers Azure Monitor / Log Analytics pour alerting (ex. handshake absent depuis > 24h sur un peer critique).

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
