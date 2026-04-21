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

    # HuggingFace model watcher
    hf_min_size_b: int = 1
    hf_max_size_b: int = 100
    hf_watch_interval_seconds: int = 86400
    hf_default_scenario: str = "scenarios/basic_8b.yaml"
    hf_watched_orgs: list[str] = [
        "meta-llama",
        "mistralai",
        "google",
        "microsoft",
        "nvidia",
        "unsloth",
        "bartowski",
        "lmstudio-community",
        "Qwen",
        "deepseek-ai",
        "BAAI",
        "internlm",
        "moonshotai",
        "coherelabs"
    ]


settings = Settings()
