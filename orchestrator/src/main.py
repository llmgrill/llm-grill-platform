import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from src.orchestrator import polling_loop
from src.routers.bench import router as bench_router
from src.routers.leaderboard import router as leaderboard_router
from src.routers.nodes import router as nodes_router
from src.routers.results import router as results_router
from src.routers.runs import router as runs_router

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task_poll = asyncio.create_task(polling_loop())
    yield
    task_poll.cancel()


app = FastAPI(title="llm-grill orchestrator", lifespan=lifespan)
app.include_router(bench_router)
app.include_router(runs_router)
app.include_router(nodes_router)
app.include_router(results_router)
app.include_router(leaderboard_router)

_RUNNER_PATH = Path(__file__).resolve().parents[1] / "runner.sh"


@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok"}


@app.get("/runner.sh", include_in_schema=False)
async def serve_runner():
    return FileResponse(_RUNNER_PATH, media_type="text/plain")
