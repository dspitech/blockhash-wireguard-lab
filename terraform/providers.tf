terraform {
  required_version = ">= 1.5.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.100"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    http = {
      source  = "hashicorp/http"
      version = "~> 3.4"
    }
  }

  # Backend recommandé en usage professionnel : état distant versionné
  # et verrouillé (évite toute corruption en travail d'équipe).
  # Décommentez et adaptez apres avoir cree le storage account dedie a l'etat :
  #
  # backend "azurerm" {
  #   resource_group_name  = "RG-Terraform-State"
  #   storage_account_name = "stblockhashtfstate"
  #   container_name       = "tfstate"
  #   key                  = "wireguard-lab.tfstate"
  # }
}

provider "azurerm" {
  features {
    resource_group {
      prevent_deletion_if_contains_resources = false
    }
  }
}
