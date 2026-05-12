"""Shared fixtures for the orchestrator test suite."""

import os

os.environ.setdefault("API_KEY", "test-key")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import src.db as _db
from src.main import app
from src.models import Base, Engine, GpuType, Node, NodeStatus, Run

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def session_factory():
    """In-memory SQLite session factory — patches src.db.AsyncSessionLocal for all repos/services."""
    engine = create_async_engine(TEST_DB_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    original = _db.AsyncSessionLocal
    _db.AsyncSessionLocal = factory
    yield factory
    _db.AsyncSessionLocal = original
    await engine.dispose()


@pytest.fixture
async def client(session_factory):
    """AsyncClient wired to an in-memory DB."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": "test-key"},
    ) as c:
        yield c


@pytest.fixture
async def provisioning_h100(session_factory):
    """A persisted H100 node in provisioning state (node exists but not yet busy)."""
    async with session_factory() as session:
        node = Node(
            id="gpu-h100-1",
            gpu_type=GpuType.H100,
            gpu_count=1,
            status=NodeStatus.provisioning,
        )
        session.add(node)
        await session.commit()
        return node.id


@pytest.fixture
async def provisioning_l40s(session_factory):
    """A persisted L40S node in provisioning state."""
    async with session_factory() as session:
        node = Node(
            id="gpu-l40s-1",
            gpu_type=GpuType.L40S,
            gpu_count=1,
            status=NodeStatus.provisioning,
        )
        session.add(node)
        await session.commit()
        return node.id


@pytest.fixture
async def queued_run(session_factory):
    """A persisted queued run targeting an H100 node (70B model)."""
    async with session_factory() as session:
        run = Run(
            model="test/model",
            model_size_b=70,
            engine=Engine.vllm,
            gpu_type_required=GpuType.H100,
            scenario_path="scenarios/basic.yaml",
        )
        session.add(run)
        await session.commit()
        return run.id
