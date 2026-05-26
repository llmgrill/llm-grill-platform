# CLAUDE.md — llm-grill-platform

Source of truth for build, run, and development. Optimized for Claude Code.

---

## Project

Benchmark pipeline for LLM inference servers on Scaleway GPU.
The orchestrator (FastAPI) queues runs, provisions ephemeral GPU VMs via Terraform, executes [`llm-grill`](https://github.com/fisheatfish/llm-grill) on each, and publishes a consolidated leaderboard to S3.

Architecture decisions: [`docs/adr/`](docs/adr/) — start with `001-automated-benchmark-site.md`.

---

## Stack

| Role                  | Tech                                | Version |
|-----------------------|-------------------------------------|---------|
| API                   | FastAPI + uvicorn                   | 0.135 / 0.44 |
| ORM / migrations      | SQLAlchemy (async) + Alembic        | 2.0 / 1.18 |
| Database              | PostgreSQL                          | 18 |
| Driver                | asyncpg (runtime) · psycopg2 (alembic) | — |
| Settings              | pydantic-settings                   | 2.13 |
| Object storage        | boto3 → Scaleway S3                 | 1.42 |
| Provisioning          | Terraform                           | ~1.6 |
| Benchmarking engine   | `llm-grill`                         | 0.1.3 |
| Logging               | loguru                              | 0.7 |
| Tests                 | pytest + pytest-asyncio + pytest-mock + aiosqlite | 9 / 1.3 / 3.15 / 0.22 |
| Lint / type-check     | ruff · ty                           | 0.15 / 0.0.34 |
| Packaging             | uv                                  | — |

---

## Structure

```
orchestrator/src/
├── main.py            # FastAPI app entrypoint
├── config.py          # Settings (pydantic-settings, env-driven)
├── auth.py            # Bearer-token auth dependency
├── db.py              # SQLAlchemy async engine + session factory
├── models.py          # ORM models
├── schemas.py         # Pydantic DTOs
├── storage.py         # S3 adapter (Scaleway)
├── orchestrator.py    # core orchestration loop
├── aggregation.py     # leaderboard computation
├── controllers/       # request handlers
├── routers/           # FastAPI routers
├── services/          # business logic (hexagonal)
├── repositories/      # DB access (hexagonal)
└── infra/             # adapters (terraform, ssh, scaleway)

orchestrator/alembic/  # DB migrations
orchestrator/tests/    # pytest

infra/
├── orchestrator-vm/   # Terraform — orchestrator VM (ephemeral)
└── gpu-vm/            # Terraform — GPU VM module (per-run)
runner/                # cloud-init / systemd runner on GPU VM

scenarios/             # llm-grill scenario YAMLs
docs/adr/              # versioned ADRs
.github/workflows/     # bench.yml + ci.yml
```

> Hexagonal naming: `Service` / `Adapter` / `Repository` / `Port`. Enforced.

---

## Make targets

### Root (`Makefile`) — Docker stack

```bash
make up                       # postgres + migration + orchestrator
make up-no-mig                # skip migrations
make up-debug                 # foreground, streaming logs
make down                     # stop containers
make down-volumes             # stop + wipe DB volume
make logs                     # tail orchestrator
make vm-shell  RUN_ID=<uuid>  # SSH into a GPU VM
make vm-logs   RUN_ID=<uuid>  # tail llmgrill-runner journal on a VM
make run-logs  RUN_ID=<uuid>  # fetch S3-uploaded runner logs
```

### `orchestrator/Makefile` — Python

```bash
make setup        # uv sync --frozen --all-groups
make setup-dev    # uv sync --frozen --group dev
make test         # pytest -v --cov=src
make lint         # ruff check --fix + ruff format
make check        # ruff + ty (CI-style, no fixes)
```

---

## Configuration

All runtime config flows through env vars (see `.env.example`). Key vars:

| Variable | Purpose |
|---|---|
| `API_KEY` | Bearer token gating mutating endpoints |
| `HF_TOKEN` | HuggingFace token (gated model downloads) |
| `SCW_ACCESS_KEY` / `SCW_SECRET_KEY` | Scaleway credentials |
| `SCW_DEFAULT_PROJECT_ID` / `SCW_DEFAULT_ORGANIZATION_ID` | Scaleway scoping |
| `SCW_BUCKET` / `SCW_REGION` | S3 destination |
| `GPU_ZONE` | Scaleway zone for GPU VMs |
| `ORCHESTRATOR_URL` | Public callback URL for GPU VMs |
| `SSH_PUBLIC_KEYS` | CSV pubkeys injected on every GPU VM |
| `RUN_RUNNING_TIMEOUT_MINUTES` | Watchdog kill threshold |
| `POSTGRES_*` | DB connection |

---

## API surface

OpenAPI / Swagger: `GET /docs` once running.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/bench` | ✅ | Queue runs for new/changed models |
| GET | `/bench/status` | — | Active/queued count, ETA |
| GET | `/leaderboard` | — | Consolidated results |
| GET | `/runs/{id}` | — | Run state + node IP |
| GET | `/runs/{id}/logs` | — | S3 logs (after completion) |
| GET | `/health` | — | Liveness |

All mutating endpoints require `Authorization: Bearer $API_KEY`.

---

## Pipeline (CI)

Trigger: push that touches `orchestrator/models.yaml`, or manual `workflow_dispatch`.

```
.github/workflows/bench.yml
  1. terraform apply           → create orchestrator VM
  2. rsync repo + write .env   → on VM
  3. docker compose up         → postgres + migrations + orchestrator
  4. POST /bench               → queue runs
  5. poll /bench/status        → wait for active=0
                                (orchestrator writes leaderboard.json to S3
                                 incrementally on each run completion)
  6. terraform destroy         → always (even on failure)
```

---

## Models list

`orchestrator/models.yaml` — single source of truth. Adding/removing a row triggers a re-bench for that model on next push.

Schema per entry:

```yaml
- model: <hf-org>/<hf-name>       # HuggingFace ID
  engine: vllm | llamacpp
  size_b: <float>                  # billions of parameters
  scenario: scenarios/ramp.yaml    # optional (default)
  gguf_file: <filename>            # llamacpp only
```

Force a full re-bench: trigger `bench` workflow manually with `force=true`.

**Cross-cycle dedup lives on S3.** A model is considered "already benched" if `s3://${SCW_BUCKET}/results/<model-slug>/<engine>/latest.meta.json` exists (slug = `model.replace("/", "__")`). Postgres is ephemeral and not consulted for dedup. To re-bench a single model without `force=true`:

```bash
aws s3 rm "s3://${SCW_BUCKET}/results/<slug>/<engine>/latest.meta.json" \
  --endpoint-url "https://s3.${SCW_REGION}.scw.cloud"
```

### Public S3 artifacts (consumed by the static frontend)

The orchestrator publishes three public-read JSON files at the bucket root. The front never reads `models.yaml` / `scenarios/*.yaml` directly — it fetches these. See `docs/frontend-plan.md § Data contract` for the full shapes.

| File | Written by | When |
|---|---|---|
| `leaderboard.json` | `storage.update_leaderboard_for` | incrementally on each successful run completion |
| `models.json` | `storage.upload_models_catalog` | on each `POST /bench`, derived from `models.yaml` |
| `scenarios.json` | `storage.upload_scenarios_catalog` | on each `POST /bench`, derived from all `scenarios/*.yaml` |

- `leaderboard.json` rows carry per-`(model, engine)` aggregates **plus** a `per_concurrency` breakdown (TTFT/TPOT/throughput per ramp level — the load curve, not just the collapsed mean).
- `models.json` is fully **derived** (no editorial fields hand-maintained in `models.yaml`): `brand` = HF org, `params_b` = `size_b`, `quantization` parsed from `gguf_file` (or `null`).
- `scenarios.json` is **directory-discovered**: drop a new `scenarios/*.yaml` and it surfaces on the next bench, no code change.

---

## Database migrations

```bash
cd orchestrator
uv run alembic revision --autogenerate -m "describe change"
uv run alembic upgrade head
```

The `migration` Docker service runs `alembic upgrade head` once at stack startup, then exits. The orchestrator service depends on its successful completion.

---

## Tests

```
orchestrator/tests/
├── conftest.py          # async session fixture (aiosqlite)
├── controllers/         # HTTP-level tests
├── services/            # business logic
├── repositories/        # DB queries
└── infra/               # terraform/ssh/scaleway adapter mocks
```

- Use **Given / When / Then** structure in docstrings.
- Use `pytest-mock` (`mocker`), not `unittest.mock`.
- Async tests via `pytest-asyncio` in auto mode.

### Mutation testing (ad-hoc, not in CI)

[`ordeal`](https://github.com/teilomillet/ordeal) finds assertions that coverage misses:
a surviving mutant means "a test still passes when this line is wrong". Run it
occasionally on the **pure-logic** modules, where the signal is reliable:

```bash
cd orchestrator
API_KEY=test-key uvx ordeal mutate src.catalog src.aggregation \
  -k "catalog or aggregation" --preset standard -w 4
```

- `API_KEY` must be set: ordeal imports the module before `conftest.py` runs.
- **Skip the DB/async repositories** (`src.repositories.*`, parts of
  `src.orchestrator`): ordeal mutates in-memory but re-runs pytest in a
  subprocess that re-imports the unmutated source, so it reports false
  "survivors" there even when the behaviour is fully tested.
- Not committed to the lockfile — invoke via `uvx` on demand.

---

## Code conventions

- **Hexagonal naming** enforced: `Service`, `Adapter`, `Repository`, `Port`.
- `from __future__ import annotations` everywhere.
- Async everywhere on the HTTP / DB I/O path.
- Input validation via Pydantic only. No defensive validation inside the core.
- Logging via `loguru` — never `print`.
- Short classes (< 80 lines), single responsibility.

---

## Commits & releases

- **Conventional Commits**: `feat:`, `fix:`, `perf:`, `refactor:`, `docs:`, `chore:`, `test:`, `ci:`.
- Open PRs against `main`; never push directly.
- No automatic release pipeline — this is an internal service, not a published package.

---

## Files not to version

Already in `.gitignore` — keep it that way:

- `.env`
- `infra/orchestrator-vm/terraform.tfvars`, `*.tfstate*`, `.terraform/`
- `__pycache__/`, `.venv/`, `.pytest_cache/`, `.ruff_cache/`
- `htmlcov/`, `.coverage`
- `.DS_Store`
- `.claude/worktrees/`
- `*.jsonl`
