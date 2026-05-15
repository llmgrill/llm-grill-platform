FROM python:3.12-slim

WORKDIR /app

ARG TERRAFORM_VERSION=1.15.3

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl unzip ca-certificates \
    && curl -fsSL -o /tmp/terraform.zip "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip" \
    && unzip /tmp/terraform.zip -d /usr/local/bin \
    && rm /tmp/terraform.zip \
    && apt-get purge -y unzip \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY orchestrator/pyproject.toml orchestrator/uv.lock ./
RUN uv sync --frozen --no-dev

COPY orchestrator/src ./src
COPY orchestrator/alembic ./alembic
COPY orchestrator/alembic.ini ./alembic.ini
COPY orchestrator/models.yaml ./models.yaml
COPY terraform ./terraform
COPY scenarios ./scenarios
COPY runner/runner.sh ./runner.sh

RUN useradd --system --no-create-home appuser && chown -R appuser /app
USER appuser

ENV UV_CACHE_DIR=/app/.cache/uv

CMD ["uv", "run", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
