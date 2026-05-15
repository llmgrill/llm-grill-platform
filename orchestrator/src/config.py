from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = ""
    postgres_user: str = "postgres"
    postgres_password: str = ""
    postgres_host: str = "localhost"
    postgres_db: str = "llmgrill"

    poll_interval_seconds: int = 10
    provision_max_attempts: int = 30
    # SSH public keys (comma-separated) injected on provisioned GPU VMs for debug access.
    ssh_public_keys: str = ""
    # Force-destroy a node if its run stays in "running" longer than this (minutes).
    run_running_timeout_minutes: int = 60

    @model_validator(mode="after")
    def build_database_url(self) -> "Settings":
        if not self.database_url:
            self.database_url = (
                f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
                f"@{self.postgres_host}/{self.postgres_db}"
            )
        return self

    # Terraform / Scaleway
    orchestrator_url: str = "http://localhost:8000"
    hf_token: str = ""
    gpu_zone: str = "fr-par-2"

    # Scaleway Object Storage
    scw_bucket: str = "llmgrill-results"
    scw_region: str = "fr-par"
    scw_access_key: str = ""
    scw_secret_key: str = ""
    api_key: str
    debug: bool = False

    # Model list (deployed alongside the orchestrator)
    models_file: Path = Path(__file__).resolve().parents[1] / "models.yaml"

    @field_validator("api_key")
    @classmethod
    def api_key_must_be_set(cls, v: str) -> str:
        if not v:
            raise ValueError("API_KEY must be set")
        return v


settings = Settings()  # ty: ignore[missing-argument]
