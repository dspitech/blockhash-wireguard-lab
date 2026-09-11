# =========================================================
# BLOCKHash - LAB WireGuard VPN
# Racine Terraform : orchestre les modules network et compute
# =========================================================

resource "azurerm_resource_group" "this" {
  name     = var.resource_group_name
  location = var.location
  tags     = var.tags
}

module "network" {
  source = "./modules/network"

  resource_group_name        = azurerm_resource_group.this.name
  location                   = azurerm_resource_group.this.location
  admin_source_ip            = var.admin_source_ip
  wireguard_client_source_ip = var.wireguard_client_source_ip
  wireguard_port              = var.wireguard_port
  dashboard_port              = var.dashboard_port
  dashboard_tls_port          = var.dashboard_tls_port
  tags                        = var.tags
}

module "compute" {
  source = "./modules/compute"

  resource_group_name = azurerm_resource_group.this.name
  location             = azurerm_resource_group.this.location
  subnet_id            = module.network.subnet_id
  vm_size              = var.vm_size
  admin_username       = var.admin_username
  admin_password       = var.admin_password
  use_ssh_key          = var.use_ssh_key
  ssh_public_key       = var.ssh_public_key
  dns_label_prefix     = var.dns_label_prefix
  tags                 = var.tags
}
