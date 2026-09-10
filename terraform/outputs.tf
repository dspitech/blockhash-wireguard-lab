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
  description = "URL du dashboard BLOCKHash - joignable UNIQUEMENT une fois connecte au VPN WireGuard (voir scripts/03-install-dashboard.sh, etape 7bis : gunicorn en loopback, Caddy expose en TLS sur l'IP privee du tunnel). Le certificat est auto-signe (tls internal) : le navigateur demandera une confirmation la premiere fois. Port TLS par defaut : 443 (variable DASHBOARD_TLS_PORT du script d'installation)."
  value       = "https://10.66.66.1"
}
