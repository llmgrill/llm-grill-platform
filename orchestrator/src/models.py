import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import Uuid


class Base(DeclarativeBase):
    pass


class RunStatus(str, enum.Enum):
    queued = "queued"
    provisioning = "provisioning"
    running = "running"
    done = "done"
    failed = "failed"


class NodeStatus(str, enum.Enum):
    provisioning = "provisioning"
    busy = "busy"
    down = "down"


class Engine(str, enum.Enum):
    vllm = "vllm"
    llamacpp = "llamacpp"


class GpuType(str, enum.Enum):
    L40S = "L40S"
    H100 = "H100"


ACTIVE_RUN_STATUSES: frozenset[RunStatus] = frozenset(
    {RunStatus.queued, RunStatus.provisioning, RunStatus.running}
)


class Node(Base):
    __tablename__ = "nodes"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    gpu_type: Mapped[GpuType] = mapped_column(Enum(GpuType), nullable=False)
    gpu_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[NodeStatus] = mapped_column(
        Enum(NodeStatus), nullable=False, default=NodeStatus.provisioning
    )
    ip_address: Mapped[str | None] = mapped_column(String, nullable=True)
    current_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(), nullable=True)


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus), nullable=False, default=RunStatus.queued
    )
    model: Mapped[str] = mapped_column(String, nullable=False)
    model_size_b: Mapped[int] = mapped_column(Integer, nullable=False)
    engine: Mapped[Engine] = mapped_column(Enum(Engine), nullable=False)
    gpu_type_required: Mapped[GpuType] = mapped_column(Enum(GpuType), nullable=False)
    gpu_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    scenario_path: Mapped[str] = mapped_column(String, nullable=False)
    gguf_file: Mapped[str | None] = mapped_column(String, nullable=True)
    results_url: Mapped[str | None] = mapped_column(String, nullable=True)
    logs_url: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    provision_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Result(Base):
    __tablename__ = "results"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("runs.id"), unique=True, nullable=False
    )
    model: Mapped[str] = mapped_column(String, nullable=False)
    engine: Mapped[str] = mapped_column(String, nullable=False)
    gpu_type: Mapped[GpuType] = mapped_column(Enum(GpuType), nullable=False)
    scenario: Mapped[str] = mapped_column(String, nullable=False)
    total_requests: Mapped[int] = mapped_column(Integer, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False)
    success_rate: Mapped[float] = mapped_column(Float, nullable=False)
    ttft_mean_s: Mapped[float] = mapped_column(Float, nullable=False)
    ttft_median_s: Mapped[float] = mapped_column(Float, nullable=False)
    ttft_p95_s: Mapped[float] = mapped_column(Float, nullable=False)
    tpot_mean_s: Mapped[float] = mapped_column(Float, nullable=False)
    e2e_mean_s: Mapped[float] = mapped_column(Float, nullable=False)
    e2e_p95_s: Mapped[float] = mapped_column(Float, nullable=False)
    tokens_per_second_mean: Mapped[float] = mapped_column(Float, nullable=False)
    total_tokens_per_second: Mapped[float] = mapped_column(Float, nullable=False)
    requests_per_second: Mapped[float] = mapped_column(Float, nullable=False)
    total_duration_s: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
