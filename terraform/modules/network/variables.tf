variable "resource_group_name" {
  description = "Nom du groupe de ressources"
  type        = string
}

variable "location" {
  description = "Région Azure"
  type        = string
}

variable "vnet_address_space" {
  description = "Espace d'adressage du VNet"
  type        = list(string)
  default     = ["10.10.0.0/24"]
}

variable "subnet_address_prefix" {
  description = "Préfixe du sous-réseau"
  type        = string
  default     = "10.10.0.0/24"
}

variable "admin_source_ips" {
  description = "Liste de CIDR IP autorisés pour le SSH et le dashboard d'administration (IP de l'opérateur + IP de la machine qui exécute 'terraform apply', pour que le provisioning SSH automatisé fonctionne quel que soit l'endroit d'où Terraform est lancé)"
  type        = list(string)
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
  description = "Port TCP interne du dashboard BLOCKHash (gunicorn, loopback uniquement)"
  type        = number
  default     = 8080
}

variable "dashboard_tls_port" {
  description = "Port TCP public du dashboard BLOCKHash (Caddy, TLS) - celui reellement ouvert dans le NSG"
  type        = number
  default     = 443
}

variable "tags" {
  description = "Tags appliqués aux ressources"
  type        = map(string)
  default     = {}
}
