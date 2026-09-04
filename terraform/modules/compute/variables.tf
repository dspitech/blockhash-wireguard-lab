variable "resource_group_name" {
  type = string
}

variable "location" {
  type = string
}

variable "subnet_id" {
  type = string
}

variable "vm_name" {
  type    = string
  default = "vm-wireguard-lab"
}

variable "vm_size" {
  type    = string
  default = "Standard_B2s"
}

variable "admin_username" {
  type    = string
  default = "wgadmin"
}

variable "admin_password" {
  type      = string
  sensitive = true
}

variable "use_ssh_key" {
  description = "Si true, authentification SSH par clé publique plutôt que mot de passe (recommandé)"
  type        = bool
  default     = false
}

variable "ssh_public_key" {
  description = "Clé publique SSH (obligatoire si use_ssh_key = true)"
  type        = string
  default     = ""
}

variable "dns_label_prefix" {
  type = string
}

variable "private_ip_address" {
  type    = string
  default = "10.10.0.10"
}

variable "tags" {
  type    = map(string)
  default = {}
}
