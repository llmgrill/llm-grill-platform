# Roadmap

## Locked-in decisions

- **`llm-grill`**: PyPI; `aggregate()` + `RequestMetrics` are stable.
- **Domain**: `llm-grill.fr` (GitHub Pages + CNAME).
- **Alerting**: GitHub email only.
- **`run_id`**: `YYYY-MM-DD-{git-sha}`.

---

## Wave status

### ✅ Wave 0 — Storage foundation
PR #1 merged (`51c7677`).
- `results/` layout, JSONL fixtures, `docs/schemas.md`.

### ✅ Wave 0.5 — Orchestrator backend
- FastAPI: runs, nodes, results, leaderboard.
- Infra: Terraform (Scaleway), HuggingFace watcher, S3 storage.
- Architecture: routers → controllers → services → repositories.

### ✅ Wave 1A — Simplified pipeline
- `models.yaml` — hardcoded list, source of truth.
- `scripts/bench.py` — diff against `results/`, POST to orchestrator.
- `scripts/wait_for_runs.py` — polls orchestrator + downloads JSONL.
- `.github/workflows/bench.yml` — triggers on `models.yaml` push + manual dispatch.

**Locked decision**: no automatic HF discovery. Adding a model = PR on `models.yaml`.

### ⏳ Wave 1B — Frontend
Starts after `feat/backend` merges; parallel with 1A.
- SvelteKit + adapter-static on `llm-grill.fr`.
- **Single page**: interactive scatter plot (X/Y configurable), filters by brand/category/model.
- Data: static JSON hardcoded in the repo (no nightly run).
- `.github/workflows/deploy.yml`.

**Locked decision**: no `/model/[slug]` or `/history` routes for now.

### 🔒 Wave 2 — Terraform infra
Blocked — Scaleway inputs needed: region, Project ID, IAM key, instance type, base image.
- `infra/orchestrator-vm/main.tf`, `variables.tf`, `outputs.tf`.
- `setup-vllm.sh`, `setup-llamacpp.sh` (cloud-init).

### 📝 001g — Secrets runbook
`docs/runbooks/secrets.md` — to be written at the end of Wave 2.

---

## Backend VM deployment

### Stack

| Component | Choice | Reason |
|-----------|--------|--------|
| Provider | Scaleway (same account as GPU nodes) | unified IAM, private network possible |
| Instance | DEV1-M or PLAY2-MICRO (2 vCPU, 4 GB RAM) | lightweight orchestrator, no compute |
| OS | Ubuntu 24.04 LTS | standard Scaleway image |
| Runtime | Docker + Docker Compose | isolation, automatic restart |
| DB | PostgreSQL 16 (container, persistent volume) | data reconstructible from S3, managed DB overkill |
| Reverse proxy | Caddy | automatic Let's Encrypt TLS, minimal config |
| Domain | `api.llm-grill.fr` | called by GPU nodes for callbacks |

### Target compose (`docker-compose.yml`)

```
orchestrator  ← FastAPI + uvicorn
postgres      ← PostgreSQL 16, named volume
caddy         ← reverse proxy TLS on api.llm-grill.fr
```

### Required environment variables

```
DATABASE_URL          postgresql+asyncpg://postgres:<pwd>@postgres/llmgrill
ORCHESTRATOR_URL      https://api.llm-grill.fr
HF_TOKEN              <huggingface token>
SCW_ACCESS_KEY        <scaleway IAM key>
SCW_SECRET_KEY        <scaleway IAM secret>
SCW_BUCKET            llmgrill-results
SCW_REGION            fr-par
GPU_ZONE              fr-par-2
```

### Files to create

- `deploy/docker-compose.yml`
- `deploy/Caddyfile`
- `deploy/.env.example`
- `orchestrator/Dockerfile`

### Open questions

- [ ] Scaleway Project ID for the backend VM (same project as GPU nodes?)
- [ ] DNS `api.llm-grill.fr` → public IP of the VM (A record to create)
- [ ] PostgreSQL backup: daily dump to S3 bucket, or unnecessary?
