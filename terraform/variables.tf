variable "resource_group_name" {
  description = "Nom du groupe de ressources Azure"
  type        = string
  default     = "RG-Lab-WireGuard"
}

variable "location" {
  description = "Région Azure de déploiement"
  type        = string
  default     = "norwayeast"
}

variable "vm_size" {
  description = "Taille de la VM Ubuntu"
  type        = string
  default     = "Standard_B2s"
}

variable "admin_username" {
  description = "Nom de l'utilisateur administrateur de la VM"
  type        = string
  default     = "wgadmin"
}

variable "admin_password" {
  description = "Mot de passe administrateur (utilisé si use_ssh_key = false)"
  type        = string
  sensitive   = true
}

variable "use_ssh_key" {
  description = "Authentification SSH par clé publique (recommandé en production)"
  type        = bool
  default     = false
}

variable "ssh_public_key" {
  description = "Clé publique SSH (obligatoire si use_ssh_key = true)"
  type        = string
  default     = ""
}

variable "dns_label_prefix" {
  description = "Préfixe DNS unique pour l'IP publique (ex: blockhash-wg-lab)"
  type        = string
}

variable "admin_source_ip" {
  description = "CIDR IP autorisé en permanence pour le SSH et le dashboard (ex: 203.0.113.10/32) — typiquement l'IP de l'opérateur pour l'accès après déploiement. Automatiquement complété par l'IP de la machine exécutant 'terraform apply' (voir auto_allow_deployer_ip) pour que le déploiement SSH automatisé fonctionne quel que soit l'endroit d'où Terraform est lancé."
  type        = string
}

variable "wireguard_client_source_ip" {
  description = "CIDR IP autorisé pour les clients WireGuard ('*' = ouvert à Internet)"
  type        = string
  default     = "*"
}

variable "wireguard_port" {
  description = "Port UDP WireGuard"
  type        = number
  default     = 51820
}

variable "dashboard_port" {
  description = "Port TCP interne du dashboard BLOCKHash (gunicorn, loopback 127.0.0.1 uniquement - jamais expose publiquement)"
  type        = number
  default     = 8080
}

variable "dashboard_tls_port" {
  description = "Port TCP public du dashboard BLOCKHash (Caddy, TLS auto-signe) - c'est ce port, pas dashboard_port, qui est joignable depuis admin_source_ip"
  type        = number
  default     = 443
}

variable "tags" {
  description = "Tags appliqués à toutes les ressources"
  type        = map(string)
  default = {
    Project    = "WireGuard-Lab"
    Department = "Formation"
    CostCenter = "BLOCKHash-Lab"
    CreatedBy  = "BLOCKHash"
    Domain     = "VPN"
    Systeme    = "Ubuntu-22.04"
  }
}

# ---------------------------------------------------------------
# Déploiement automatisé (provisioning distant post-création VM)
# ---------------------------------------------------------------
variable "auto_deploy" {
  description = "Si vrai, Terraform se connecte en SSH à la VM juste créée et exécute automatiquement le clonage du dépôt + les scripts d'installation (01, 03, 04). Mettre à faux pour ne provisionner que l'infrastructure et déployer manuellement."
  type        = bool
  default     = true
}

variable "auto_allow_deployer_ip" {
  description = "Si vrai (défaut), Terraform détecte l'IP publique de la machine qui exécute 'terraform apply' et l'ajoute automatiquement aux règles NSG admin (SSH + dashboard), en plus de admin_source_ip. Évite l'erreur 'dial tcp ...:22: i/o timeout' lorsque terraform apply est lancé depuis une machine différente de celle indiquée dans admin_source_ip. Mettre à faux si la détection d'IP publique n'est pas fiable dans votre environnement (ex : CI derrière un NAT partagé) — dans ce cas, admin_source_ip doit inclure l'IP exacte du runner."
  type        = bool
  default     = true
}

variable "repo_url" {
  description = "URL du dépôt Git à cloner sur la VM pour le déploiement automatisé"
  type        = string
  default     = "https://github.com/dspitech/blockhash-wireguard-lab.git"
}

variable "ssh_private_key_path" {
  description = "Chemin local vers la clé privée SSH correspondant à ssh_public_key, utilisée par Terraform pour se connecter à la VM (requis si use_ssh_key = true). Laisser vide pour utiliser l'agent SSH local (ssh-agent) à la place."
  type        = string
  default     = ""
}

variable "dashboard_admin_username" {
  description = "Nom d'utilisateur du compte administrateur du dashboard BLOCKHash, créé automatiquement lors du déploiement"
  type        = string
  default     = "admin"
}
