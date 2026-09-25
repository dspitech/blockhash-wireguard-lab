# =========================================================
# BLOCKHash - LAB WireGuard VPN
# Racine Terraform : orchestre les modules network et compute
# =========================================================

resource "azurerm_resource_group" "this" {
  name     = var.resource_group_name
  location = var.location
  tags     = var.tags
}

# ---------------------------------------------------------------
# Detection de l'IP publique de la machine qui execute "terraform
# apply". Necessaire car le NSG restreint SSH/HTTPS admin a une
# liste d'IP explicite (var.admin_source_ip) : si ce champ contient
# l'IP de l'operateur mais que "terraform apply" tourne depuis une
# autre machine (poste different, VM bastion, CI/CD...), le
# provisioner remote-exec de null_resource.deploy se voit bloque
# silencieusement par le NSG - symptome typique : timeout SSH
# ("dial tcp <ip>:22: i/o timeout") plutot qu'un rejet immediat.
# On ajoute donc automatiquement l'IP du "deployer" a la liste
# autorisee. Desactivable via auto_allow_deployer_ip = false si
# l'IP de sortie n'est pas fiable (ex: CI derriere un NAT partage).
# ---------------------------------------------------------------
data "http" "deployer_ip" {
  count = var.auto_allow_deployer_ip ? 1 : 0
  url   = "https://api.ipify.org?format=text"
}

locals {
  deployer_cidr = var.auto_allow_deployer_ip ? ["${trimspace(data.http.deployer_ip[0].response_body)}/32"] : []
  # distinct() dedupe si admin_source_ip == IP du deployer (cas courant :
  # l'operateur lance terraform depuis son propre poste).
  admin_source_ips = distinct(concat([var.admin_source_ip], local.deployer_cidr))
}

module "network" {
  source = "./modules/network"

  resource_group_name        = azurerm_resource_group.this.name
  location                   = azurerm_resource_group.this.location
  admin_source_ips           = local.admin_source_ips
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

# ---------------------------------------------------------------
# Mot de passe du compte admin du dashboard BLOCKHash, genere par
# Terraform (jamais en clair dans le code) puis transmis au script
# d'installation via une variable d'environnement - voir
# scripts/03-install-dashboard.sh, qui la reprend telle quelle au
# lieu d'en generer une aleatoirement si elle est deja definie.
# ---------------------------------------------------------------
resource "random_password" "dashboard_admin" {
  length  = 20
  special = true
  # Jeu de caracteres speciaux restreint : evite les caracteres qui posent
  # probleme une fois injectes dans une commande shell distante (remote-exec).
  override_special = "-_=+"
}

# ---------------------------------------------------------------
# Deploiement automatise : une fois la VM prete, on s'y connecte en
# SSH pour cloner le depot et executer, dans l'ordre, les scripts
# d'installation du serveur WireGuard, du dashboard et de la
# journalisation/supervision - equivalent de la sequence manuelle :
#
#   git clone <repo_url> && cd blockhash-wireguard-lab/scripts \
#     && chmod +x *.sh \
#     && sudo ./01-install-wireguard-server.sh \
#     && sudo ./03-install-dashboard.sh <dashboard_port> \
#     && sudo ./04-logging-monitoring.sh
#
# Desactivable via auto_deploy = false (voir variables.tf) pour ne
# provisionner que l'infrastructure et deployer a la main.
# ---------------------------------------------------------------
resource "null_resource" "deploy" {
  count = var.auto_deploy ? 1 : 0

  # Garantit que le NSG (avec l'IP du deployer autorisee, voir plus haut)
  # est bien applique avant toute tentative de connexion SSH.
  depends_on = [module.network]

  # Redeclenche le provisioning si la VM est recreee ou si le depot/port cible change.
  triggers = {
    vm_id          = module.compute.vm_id
    repo_url       = var.repo_url
    dashboard_port = var.dashboard_port
  }

  connection {
    type        = "ssh"
    host        = module.compute.public_ip_address
    user        = var.admin_username
    password    = var.use_ssh_key ? null : var.admin_password
    private_key = var.use_ssh_key && var.ssh_private_key_path != "" ? try(file(var.ssh_private_key_path), null) : null
    agent       = var.use_ssh_key && var.ssh_private_key_path == ""
    # Delai genereux : une VM qui vient d'etre creee peut prendre plusieurs
    # minutes avant que sshd soit joignable (boot + cloud-init). Le
    # provisioner reessaie automatiquement jusqu'a expiration du delai.
    timeout = "10m"
  }

  # Attend que cloud-init (paquets systeme, git, python3...) ait fini avant
  # de lancer le clone + les scripts, pour eviter une course au demarrage.
  # NB : 03-install-dashboard.sh s'attend a trouver ./dashboard comme
  # dossier voisin (cp -r ./dashboard/* ...) : il doit donc etre lance
  # depuis la racine du depot, pas depuis scripts/ comme 01 et 04.
  #
  # Chaque etape est enveloppee dans `timeout Nm ... </dev/null` :
  # - `</dev/null` coupe l'entree standard, pour qu'une eventuelle invite
  #   interactive imprevue (apt/debconf/needrestart...) recoive un EOF
  #   immediat plutot que d'attendre indefiniment une reponse qui ne viendra
  #   jamais (cause du blocage "Still creating..." corrige ici - voir
  #   cloud-init.yaml.tpl pour le correctif needrestart lui-meme) ;
  # - `timeout Nm` est un filet de securite : si un futur imprevu bloque
  #   quand meme la commande, l'etape echoue proprement au bout de N minutes
  #   au lieu de bloquer terraform apply indefiniment.
  provisioner "remote-exec" {
    inline = [
      "sudo cloud-init status --wait || true",
      "rm -rf ~/blockhash-wireguard-lab",
      "timeout 5m git clone ${var.repo_url} </dev/null",
      "cd ~/blockhash-wireguard-lab/scripts && chmod +x *.sh",
      "cd ~/blockhash-wireguard-lab/scripts && sudo timeout 15m ./01-install-wireguard-server.sh </dev/null",
      "cd ~/blockhash-wireguard-lab && sudo ADMIN_SOURCE_IP='${var.admin_source_ip}' DASHBOARD_USERNAME='${var.dashboard_admin_username}' DASHBOARD_PASSWORD='${random_password.dashboard_admin.result}' timeout 15m ./scripts/03-install-dashboard.sh ${var.dashboard_port} </dev/null",
      "cd ~/blockhash-wireguard-lab/scripts && sudo timeout 10m ./04-logging-monitoring.sh </dev/null",
    ]
  }
}
