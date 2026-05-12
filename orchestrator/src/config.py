from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost/llmgrill"
    poll_interval_seconds: int = 10

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

    # Model list (deployed alongside the orchestrator)
    models_file: Path = Path(__file__).resolve().parents[1] / "models.yaml"

    @field_validator("api_key")
    @classmethod
    def api_key_must_be_set(cls, v: str) -> str:
        if not v:
            raise ValueError("API_KEY must be set")
        return v


settings = Settings() # ty: ignore[missing-argument]
