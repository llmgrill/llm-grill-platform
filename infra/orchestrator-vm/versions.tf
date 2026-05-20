terraform {
  required_version = ">= 1.6.0"

  required_providers {
    scaleway = {
      source  = "scaleway/scaleway"
      version = "~> 2.50"
    }
  }

  # Scaleway S3-compatible backend — bucket must exist before `terraform init`
  # Create it once manually:
  #   aws s3api create-bucket --bucket llmgrill-tfstate --endpoint-url https://s3.fr-par.scw.cloud
  # Then set env vars: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
  backend "s3" {
    bucket                      = "llmgrill-tfstate"
    key                         = "infra/terraform.tfstate"
    region                      = "fr-par"
    endpoint                    = "https://s3.fr-par.scw.cloud"
    skip_credentials_validation = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
    force_path_style            = true
  }
}

provider "scaleway" {
  region = var.region
  zone   = var.zone
}
