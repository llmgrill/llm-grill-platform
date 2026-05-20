output "instance_id" {
  description = "Scaleway instance ID"
  value       = scaleway_instance_server.gpu.id
}

output "public_ip" {
  description = "Public IP of the GPU node"
  value       = scaleway_instance_ip.gpu.address
}
