# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it responsibly:

1. **Do NOT open a public issue.**
2. Email the maintainers or use [GitHub's private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability).
3. Include a description, steps to reproduce, and potential impact.

We will acknowledge receipt within 48 hours and aim to provide a fix within 7 days for critical issues.

## Scope

The following are in scope:

- Leakage of cloud credentials (`SCW_*`, `HF_TOKEN`, `API_KEY`) through logs, error responses, or stored artefacts.
- Unauthorised access to the orchestrator API (auth bypass on `/bench`, `/runs/*`).
- Command/SQL injection via `models.yaml`, scenario YAMLs, or HTTP payloads.
- Privilege escalation on provisioned GPU VMs.
- Terraform state exposure (the state file may contain Scaleway IDs and IPs).
- Vulnerable dependencies (`pip-audit`, `trivy` on the Docker images).

Out of scope:

- Vulnerabilities in upstream inference servers (vLLM, llama.cpp, …) — report those upstream.
- DoS via legitimate benchmark workloads (this is the intended use).

## Best practices for operators

- **Never commit `.env`** or `infra/orchestrator-vm/terraform.tfvars` — they contain secrets and personal data. Both are gitignored.
- **Rotate `API_KEY`** if a CI run leaked logs externally. Generate with `openssl rand -hex 32`.
- **Use a remote Terraform backend** with state encryption for shared deployments.
- **Restrict `admin_cidrs`** in `infra/orchestrator-vm/terraform.tfvars` to your egress IPs. The CI default of `0.0.0.0/0` is permissive on purpose (GitHub-hosted runners have no fixed IP range).
- **Scope HuggingFace tokens** to the minimum (read-only, gated-model access).
- **Audit `SSH_PUBLIC_KEYS`** regularly — those keys are injected on every provisioned GPU VM.
- **Use Scaleway IAM** to scope `SCW_*` keys to a single project, ideally with object-storage + instance permissions only.
