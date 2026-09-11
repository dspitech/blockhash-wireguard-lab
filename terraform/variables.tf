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
  description = "CIDR IP autorisé pour le SSH et le dashboard (ex: 203.0.113.10/32)"
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
