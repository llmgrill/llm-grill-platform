locals {
  name = "llmgrill-${var.run_id}"
}

resource "scaleway_iam_ssh_key" "keys" {
  count      = length(var.ssh_public_keys)
  name       = "${local.name}-key-${count.index}"
  public_key = var.ssh_public_keys[count.index]
}

resource "scaleway_instance_ip" "gpu" {}

resource "scaleway_instance_server" "gpu" {
  name  = local.name
  type  = var.instance_type
  image = "ubuntu_noble_gpu_os_13_nvidia"
  zone  = var.gpu_zone

  ip_id = scaleway_instance_ip.gpu.id

  root_volume {
    size_in_gb = 250
  }

  user_data = {
    "cloud-init" = templatefile("${path.module}/cloud-init.tpl.yaml", {
      run_id               = var.run_id
      orchestrator_url     = var.orchestrator_url
      hf_token             = var.hf_token
      orchestrator_api_key = var.orchestrator_api_key
      model                = var.model
      engine               = var.engine
      scenario_path        = var.scenario_path
      gguf_file            = var.gguf_file
      scenario_content     = var.scenario_content
      runner_script        = file("${path.module}/runner.sh")
    })
  }
}
