#!/usr/bin/env bash
# =========================================================
#  BLOCKHash - LAB WireGuard VPN
#  Assistant de déploiement Terraform (Bash)
#  Prerequis : Terraform CLI installe, session 'az login' active
# =========================================================
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v terraform >/dev/null 2>&1; then
  echo -e "\033[31mTerraform n'est pas installe ou absent du PATH. Voir https://developer.hashicorp.com/terraform/install\033[0m"
  exit 1
fi

if [ ! -f "./terraform.tfvars" ]; then
  echo -e "\033[33mFichier terraform.tfvars introuvable.\033[0m"
  echo -e "\033[33mCopiez terraform.tfvars.example vers terraform.tfvars et personnalisez-le avant de continuer.\033[0m"
  exit 1
fi

echo -e "\033[36m== Authentification Azure ==\033[0m"
if ! az account show >/dev/null 2>&1; then
  az login
fi

echo -e "\033[36m== terraform init ==\033[0m"
terraform init

echo -e "\033[36m== terraform plan ==\033[0m"
terraform plan -out tfplan

echo ""
read -rp "Appliquer ce plan ? (o/N) " confirm
if [[ "$confirm" == "o" || "$confirm" == "O" ]]; then
  terraform apply tfplan

  echo -e "\n\033[32m=== INFORMATIONS DE CONNEXION ===\033[0m"
  terraform output

  echo -e "\n\033[32m=== ACCES AU DASHBOARD BLOCKHash ===\033[0m"
  echo "Lien         : $(terraform output -raw dashboard_url)"
  echo "Identifiant  : $(terraform output -raw dashboard_username)"
  echo "Mot de passe : $(terraform output -raw dashboard_password)"
  echo -e "\n\033[33m(certificat auto-signe : votre navigateur demandera une confirmation la premiere fois)\033[0m"
else
  echo -e "\033[33mDeploiement annule.\033[0m"
fi
