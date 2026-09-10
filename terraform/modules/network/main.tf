# =========================================================
# Module : network
# Crée le VNet, le sous-réseau et le NSG du LAB WireGuard
# =========================================================

resource "azurerm_network_security_group" "this" {
  name                = "nsg-wireguard-lab"
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags

  security_rule {
    name                       = "AllowSSH-Admin"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "22"
    source_address_prefix      = var.admin_source_ip
    destination_address_prefix = "*"
    description                = "Acces SSH restreint a l IP d administration"
  }

  security_rule {
    name                       = "AllowWireGuard"
    priority                   = 110
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Udp"
    source_port_range          = "*"
    destination_port_range     = tostring(var.wireguard_port)
    source_address_prefix      = var.wireguard_client_source_ip
    destination_address_prefix = "*"
    description                = "Tunnel WireGuard (UDP)"
  }

  # NOTE SECURITE (voir README 7.3bis / scripts/03-install-dashboard.sh
  # etape 7bis) : le dashboard BLOCKHash n'ecoute plus sur une interface
  # publique. gunicorn est en loopback pur (127.0.0.1) et Caddy expose le
  # dashboard en TLS uniquement sur l'IP privee du tunnel WireGuard
  # (10.66.66.1) - donc uniquement joignable en etant deja connecte au VPN.
  # Aucune regle NSG entrante n'est donc necessaire pour ce port : on ne
  # garde QUE SSH (admin) et WireGuard (UDP) en entree publique, ce qui
  # reduit la surface d'attaque au strict minimum. Si vous revenez a une
  # exposition directe (sans Caddy), reintroduisez une regle equivalente
  # a AllowDashboard-Admin ci-dessous, restreinte a var.admin_source_ip.

  security_rule {
    name                       = "DenyAllOtherInbound"
    priority                   = 4096
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
    description                = "Bloque tout le reste du trafic entrant"
  }
}

resource "azurerm_virtual_network" "this" {
  name                = "vnet-wireguard-lab"
  location            = var.location
  resource_group_name = var.resource_group_name
  address_space       = var.vnet_address_space
  tags                = var.tags
}

resource "azurerm_subnet" "this" {
  name                 = "snet-wireguard"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = [var.subnet_address_prefix]
}

resource "azurerm_subnet_network_security_group_association" "this" {
  subnet_id                 = azurerm_subnet.this.id
  network_security_group_id = azurerm_network_security_group.this.id
}
