terraform {
  required_version = ">= 1.6.0"

  required_providers {
    scaleway = {
      source  = "scaleway/scaleway"
      version = "~> 2.50"
    }
  }
}

provider "scaleway" {
  zone   = var.gpu_zone
  region = substr(var.gpu_zone, 0, length(var.gpu_zone) - 2)
}
