import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from src.models import Engine, GpuType, NodeStatus, RunStatus


class RunCreate(BaseModel):
    model: str
    model_size_b: int = Field(gt=0, description="Model size in billions of parameters")
    engine: Engine
    scenario_path: str
    gguf_file: str | None = None


class RunComplete(BaseModel):
    results_jsonl: str


class RunFail(BaseModel):
    error_message: str


class RunRead(BaseModel):
    id: uuid.UUID
    status: RunStatus
    model: str
    model_size_b: int
    engine: Engine
    gpu_type_required: GpuType
    gpu_count: int
    scenario_path: str
    gguf_file: str | None
    results_url: str | None
    logs_url: str | None
    error_message: str | None
    node_ip: str | None = None
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None

    model_config = {"from_attributes": True}


class ResultRead(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    model: str
    engine: str
    gpu_type: GpuType
    scenario: str
    total_requests: int
    success_count: int
    error_count: int
    success_rate: float
    ttft_mean_s: float
    ttft_median_s: float
    ttft_p95_s: float
    tpot_mean_s: float
    e2e_mean_s: float
    e2e_p95_s: float
    tokens_per_second_mean: float
    total_tokens_per_second: float
    requests_per_second: float
    total_duration_s: float
    created_at: datetime

    model_config = {"from_attributes": True}


class LeaderboardEntry(BaseModel):
    model: str
    engine: str
    gpu_type: GpuType
    tokens_per_second_mean: float
    total_tokens_per_second: float
    requests_per_second: float
    e2e_p95_s: float
    ttft_p95_s: float
    success_rate: float
    run_id: uuid.UUID
    measured_at: datetime = Field(alias="created_at")

    model_config = {"from_attributes": True, "populate_by_name": True}


class CompletedRunMeta(BaseModel):
    """Payload of `latest.meta.json` — the S3 dedup signal for a (model, engine)."""

    run_id: uuid.UUID
    model: str
    engine: str
    scenario: str
    completed_at: datetime
    git_sha: str | None = None


class NodeCreate(BaseModel):
    id: str
    gpu_type: GpuType
    gpu_count: int = Field(default=1, gt=0)


class NodeRead(BaseModel):
    id: str
    gpu_type: GpuType
    gpu_count: int
    status: NodeStatus
    ip_address: str | None
    current_run_id: uuid.UUID | None

    model_config = {"from_attributes": True}
