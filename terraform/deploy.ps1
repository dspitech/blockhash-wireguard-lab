# =========================================================
#  BLOCKHash - LAB WireGuard VPN
#  Assistant de déploiement Terraform (PowerShell)
#  Prerequis : Terraform CLI installe, session 'az login' active
# =========================================================

if (-not (Get-Command terraform -ErrorAction SilentlyContinue)) {
  Write-Host "Terraform n'est pas installe ou absent du PATH. Voir https://developer.hashicorp.com/terraform/install" -ForegroundColor Red
  exit 1
}

if (-not (Test-Path "./terraform.tfvars")) {
  Write-Host "Fichier terraform.tfvars introuvable." -ForegroundColor Yellow
  Write-Host "Copiez terraform.tfvars.example vers terraform.tfvars et personnalisez-le avant de continuer." -ForegroundColor Yellow
  exit 1
}

Write-Host "== Authentification Azure ==" -ForegroundColor Cyan
az account show 2>$null
if ($LASTEXITCODE -ne 0) {
  az login
}

Write-Host "== terraform init ==" -ForegroundColor Cyan
terraform init

Write-Host "== terraform plan ==" -ForegroundColor Cyan
terraform plan -out tfplan

Write-Host ""
$confirm = Read-Host "Appliquer ce plan ? (o/N)"
if ($confirm -eq "o" -or $confirm -eq "O") {
  terraform apply tfplan

  Write-Host "`n=== INFORMATIONS DE CONNEXION ===" -ForegroundColor Green
  terraform output

  Write-Host "`n=== ACCES AU DASHBOARD BLOCKHash ===" -ForegroundColor Green
  Write-Host ("Lien      : " + (terraform output -raw dashboard_url))
  Write-Host ("Identifiant : " + (terraform output -raw dashboard_username))
  Write-Host ("Mot de passe : " + (terraform output -raw dashboard_password))
  Write-Host "`n(certificat auto-signe : votre navigateur demandera une confirmation la premiere fois)" -ForegroundColor Yellow
}
else {
  Write-Host "Deploiement annule." -ForegroundColor Yellow
}
