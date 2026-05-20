locals {
  name = "llmgrill-orchestrator"
}

# ── Results bucket ────────────────────────────────────────────────────────────
# Stores per-run results.jsonl and runner logs uploaded by the orchestrator.
# Independent of the VM lifecycle; protected from accidental destroy.

resource "scaleway_object_bucket" "results" {
  name   = var.results_bucket_name
  region = var.region

  lifecycle {
    prevent_destroy = true
  }
}

# ── Security group ────────────────────────────────────────────────────────────

resource "scaleway_instance_security_group" "orchestrator" {
  name                    = local.name
  inbound_default_policy  = "drop"
  outbound_default_policy = "accept"

  inbound_rule {
    action   = "accept"
    port     = 8000
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
      ssh_public_keys = var.ssh_public_keys
    })
  }
}
