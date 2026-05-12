output "public_ip" {
  description = "Public IP of the orchestrator VM — set this as your DNS A record and DEPLOY_HOST secret"
  value       = scaleway_instance_ip.orchestrator.address
}

output "instance_id" {
  description = "Scaleway instance ID"
  value       = scaleway_instance_server.orchestrator.id
}
