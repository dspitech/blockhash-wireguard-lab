output "vm_public_ip" {
  description = "IP publique de la VM WireGuard"
  value       = module.compute.public_ip_address
}

output "vm_fqdn" {
  description = "Nom DNS public de la VM"
  value       = module.compute.fqdn
}

output "ssh_command" {
  description = "Commande de connexion SSH"
  value       = "ssh ${var.admin_username}@${module.compute.fqdn}"
}

output "dashboard_url" {
  description = "URL du dashboard BLOCKHash - joignable directement via l'IP publique de la VM (restreinte a admin_source_ip au niveau du NSG, voir dashboard_tls_port), sans necessite d'etre connecte au VPN WireGuard au prealable. Authentification par identifiant + cle (ecran de connexion, voir /etc/blockhash/dashboard.env). Certificat auto-signe (tls internal, scripts/03-install-dashboard.sh etape 7bis) : le navigateur demandera une confirmation la premiere fois."
  value       = "https://${module.compute.public_ip_address}:${var.dashboard_tls_port}"
}

output "dashboard_username" {
  description = "Identifiant du compte administrateur du dashboard BLOCKHash (valable uniquement si auto_deploy = true)"
  value       = var.auto_deploy ? var.dashboard_admin_username : null
}

output "dashboard_password" {
  description = "Mot de passe du compte administrateur du dashboard BLOCKHash, genere automatiquement par Terraform (valable uniquement si auto_deploy = true). Affichez-le avec : terraform output -raw dashboard_password"
  value       = var.auto_deploy ? random_password.dashboard_admin.result : null
  sensitive   = true
}
