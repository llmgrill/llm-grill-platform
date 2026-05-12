FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY orchestrator/pyproject.toml orchestrator/uv.lock ./
RUN uv sync --frozen --no-dev

COPY orchestrator/src ./src
COPY orchestrator/alembic ./alembic
COPY orchestrator/alembic.ini ./alembic.ini
COPY orchestrator/models.yaml ./models.yaml
COPY runner/runner.sh ./runner.sh

RUN useradd --system --no-create-home appuser && chown -R appuser /app
USER appuser

CMD ["uv", "run", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
