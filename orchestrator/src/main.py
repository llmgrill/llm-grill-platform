import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.config import settings
from src.logging_config import setup_logging
from src.orchestrator import polling_loop
from src.routers.bench import router as bench_router
from src.routers.leaderboard import router as leaderboard_router
from src.routers.nodes import router as nodes_router
from src.routers.results import router as results_router
from src.routers.runs import router as runs_router

setup_logging("DEBUG" if settings.debug else "INFO")


@asynccontextmanager
async def lifespan(app: FastAPI):
    task_poll = asyncio.create_task(polling_loop())
    yield
    task_poll.cancel()


app = FastAPI(
    title="llm-grill orchestrator",
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)
app.include_router(bench_router)
app.include_router(runs_router)
app.include_router(nodes_router)
app.include_router(results_router)
app.include_router(leaderboard_router)


@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok"}
