variable "region" {
  description = "Scaleway region"
  type        = string
  default     = "fr-par"
}

variable "zone" {
  description = "Scaleway zone for the orchestrator VM"
  type        = string
  default     = "fr-par-1"
}

variable "instance_type" {
  description = "Scaleway instance type (DEV1-M = 3 vCPU / 4 GB, PLAY2-MICRO = 1 vCPU / 1 GB)"
  type        = string
  default     = "DEV1-M"
}

variable "ssh_public_keys" {
  description = "SSH public keys allowed to connect as the deploy user"
  type        = list(string)
}

variable "admin_cidrs" {
  description = "CIDR blocks allowed to reach port 22 (SSH). Restrict to your static IPs."
  type        = list(string)
}

variable "deploy_user" {
  description = "Linux user created for CI deployments"
  type        = string
  default     = "deploy"
}
