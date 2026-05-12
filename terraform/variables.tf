variable "run_id" {
  description = "UUID of the run this node is provisioned for"
  type        = string
}

variable "gpu_type" {
  description = "GPU type: L40S or H100"
  type        = string
  validation {
    condition     = contains(["L40S", "H100"], var.gpu_type)
    error_message = "gpu_type must be L40S or H100"
  }
}

variable "instance_type" {
  description = "Scaleway instance SKU"
  type        = string
}

variable "orchestrator_url" {
  description = "Base URL of the orchestrator API (reachable from the GPU node)"
  type        = string
}

variable "hf_token" {
  description = "HuggingFace token for model download"
  type        = string
  sensitive   = true
}

variable "gpu_zone" {
  description = "Scaleway zone for the GPU instance"
  type        = string
  default     = "fr-par-2"
  validation {
    condition     = can(regex("^(fr-par|nl-ams|pl-waw)-[1-3]$", var.gpu_zone))
    error_message = "gpu_zone must match (fr-par|nl-ams|pl-waw)-[1-3]"
  }
}

variable "orchestrator_api_key" {
  description = "API key for authenticating against the orchestrator"
  type        = string
  sensitive   = true
  default     = ""
}

variable "ssh_public_keys" {
  description = "SSH public keys for emergency access"
  type        = list(string)
  default     = []
}
