# llm-grill-platform

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)

Cloud orchestrator that runs [`llm-grill`](https://github.com/fisheatfish/llm-grill) benchmarks across a curated model list on **Scaleway GPU**, then publishes a consolidated leaderboard to S3.

Provisions **ephemeral GPU VMs** via Terraform, runs the bench, uploads results, tears the VMs down — driven by `models.yaml` + GitHub Actions.

---

## Install

Requires **Docker**, **Python 3.12+**, and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/llmgrill/llm-grill-platform.git
cd llm-grill-platform
cp .env.example .env        # fill in API_KEY, HF_TOKEN, SCW_*
```

---

## Quick start

**1. Start the stack**

```bash
make up                     # postgres + migrations + orchestrator on :8000
make logs                   # tail orchestrator
```

**2. Open the API**

```
http://localhost:8000/docs
```

**3. Queue a bench run**

```bash
curl -X POST http://localhost:8000/bench \
  -H "Authorization: Bearer $API_KEY"
```

**4. Tear down**

```bash
make down                   # stop · make down-volumes to wipe DB
```

---

## Adding a model to the bench

Edit [`orchestrator/models.yaml`](orchestrator/models.yaml) and open a PR. On merge to `main`, the workflow runs the new model and republishes the leaderboard.

```yaml
- model: meta-llama/Llama-3.1-8B-Instruct
  engine: vllm           # vllm | llamacpp
  size_b: 8
  scenario: scenarios/ramp.yaml   # optional
```

---

## Documentation

| File | Audience |
|---|---|
| [CLAUDE.md](CLAUDE.md) | full technical reference — architecture, env vars, endpoints, conventions |
| [`docs/adr/`](docs/adr/) | architecture decision records |
| [CONTRIBUTING.md](CONTRIBUTING.md) | dev workflow |
| [SECURITY.md](SECURITY.md) | vulnerability reporting |

---

## License

Apache 2.0 — see [LICENSE](LICENSE).
