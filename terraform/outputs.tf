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
  description = "URL du dashboard BLOCKHash"
  value       = "http://${module.compute.fqdn}:${var.dashboard_port}"
}
