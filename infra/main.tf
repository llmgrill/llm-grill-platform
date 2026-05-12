locals {
  name = "llmgrill-orchestrator"
}

# ── Security group ────────────────────────────────────────────────────────────

resource "scaleway_instance_security_group" "orchestrator" {
  name                    = local.name
  inbound_default_policy  = "drop"
  outbound_default_policy = "accept"

  inbound_rule {
    action   = "accept"
    port     = 80
    protocol = "TCP"
  }

  inbound_rule {
    action   = "accept"
    port     = 443
    protocol = "TCP"
  }

  dynamic "inbound_rule" {
    for_each = var.admin_cidrs
    content {
      action   = "accept"
      port     = 22
      protocol = "TCP"
      ip_range = inbound_rule.value
    }
  }
}

# ── Public IP ─────────────────────────────────────────────────────────────────

resource "scaleway_instance_ip" "orchestrator" {}

# ── VM ────────────────────────────────────────────────────────────────────────

resource "scaleway_instance_server" "orchestrator" {
  name              = local.name
  type              = var.instance_type
  image             = "ubuntu_noble"
  zone              = var.zone
  ip_id             = scaleway_instance_ip.orchestrator.id
  security_group_id = scaleway_instance_security_group.orchestrator.id

  root_volume {
    size_in_gb = 40
  }

  user_data = {
    "cloud-init" = templatefile("${path.module}/cloud-init.tpl.yaml", {
      deploy_user     = var.deploy_user
      ssh_public_keys = var.ssh_public_keys
    })
  }
}
