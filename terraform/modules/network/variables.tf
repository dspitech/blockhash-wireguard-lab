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

variable "admin_source_ip" {
  description = "CIDR IP autorisé pour le SSH et le dashboard d'administration"
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
  description = "Port TCP du dashboard BLOCKHash (API + interface web)"
  type        = number
  default     = 8080
}

variable "tags" {
  description = "Tags appliqués aux ressources"
  type        = map(string)
  default     = {}
}
