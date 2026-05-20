variable "region" {
  description = "Scaleway region"
  type        = string
  default     = "fr-par"
}

variable "zone" {
  description = "Scaleway zone for the orchestrator VM"
  type        = string
  default     = "fr-par-2"
}

variable "instance_type" {
  description = "Scaleway instance type"
  type        = string
  default     = "DEV1-S"
}

variable "ssh_public_keys" {
  description = "SSH public keys allowed to connect as the deploy user"
  type        = list(string)
}

variable "admin_cidrs" {
  description = "CIDR blocks allowed to reach port 22 (SSH). Restrict to your static IPs."
  type        = list(string)
}

variable "results_bucket_name" {
  description = "Scaleway Object Storage bucket for per-run results + logs"
  type        = string
  default     = "llmgrill-results"
}
