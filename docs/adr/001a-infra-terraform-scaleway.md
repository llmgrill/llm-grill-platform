# ADR 001a: Infrastructure — Terraform + Scaleway H100

**Date:** 2026-03-25
**Status:** Validated
**Parent:** [ADR 001](001-automated-benchmark-site.md)

---

## Context

The nightly pipeline needs H100 GPU instances to run benchmarks. Requirements:

- Provisioned on demand (no permanent infra).
- Full SSH access (for `nvidia-smi`, GPU monitoring).
- 2 backends (vLLM, llama.cpp) in parallel to minimize per-model wall time.

## Options Considered

| Option | Description | Verdict |
|--------|-------------|---------|
| **A. Terraform + Scaleway, 2 parallel instances** | 1 H100 per backend, Terraform manages lifecycle | **Chosen** |
| B. Single sequential instance | Backends run one after another | Rejected: 2× slower (~30 min vs ~15 min), same total cost |
| C. Scaleway Python SDK (no Terraform) | Provision from `run.py` directly | Rejected: Terraform is declarative, handles failure cleanup better, infra is versionable |

## Decision

**Option A**: 2 parallel H100 instances via Terraform + Scaleway.

## Design

**Structure**: `infra/orchestrator-vm/` holds the Terraform for the ephemeral orchestrator VM. `infra/gpu-vm/` holds the Terraform module instantiated once per GPU run (`main.tf`, `variables.tf`, `outputs.tf`, `cloud-init.tpl.yaml`).

**Provisioning**: Terraform creates N `H100-1-80G` instances via `for_each` on the backends list. Each instance gets a cloud-init that installs CUDA, Python, `llm-grill`, the relevant backend, and downloads the model from HuggingFace.

**GGUF handling**: if a model has no GGUF variant on HuggingFace, `discover.py` excludes `llamacpp` → only 1 instance is created (vLLM only).

**Cleanup**: `terraform destroy` is always called, even on error (`try/finally` in `run.py`). Global 60 min timeout per model. Instances have no persistent volumes — fully ephemeral.

## Consequences

| | |
|---|---|
| **+** | 2× faster than sequential, full backend isolation, infra as code, guaranteed cleanup |
| **−** | 2 instances consume Scaleway quota faster; model downloaded 2× (acceptable — HF downloads are fast on Scaleway) |
| **Cost** | ~$1.5/model (2 machines × ~15 min × H100 spot price) = same as sequential |
