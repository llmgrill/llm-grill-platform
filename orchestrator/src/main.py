import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from src.db import AsyncSessionLocal, engine
from src.models import Base
from src.orchestrator import polling_loop
from src.routers.nodes import router as nodes_router
from src.routers.results import router as results_router
from src.routers.runs import router as runs_router
from src.watcher import watching_loop

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    task_poll = asyncio.create_task(polling_loop(AsyncSessionLocal))
    task_watch = asyncio.create_task(watching_loop(AsyncSessionLocal))
    yield
    task_poll.cancel()
    task_watch.cancel()
    await engine.dispose()


app = FastAPI(title="llm-grill orchestrator", lifespan=lifespan)
app.include_router(runs_router)
app.include_router(nodes_router)
app.include_router(results_router)

_RUNNER_PATH = Path(__file__).resolve().parents[3] / "runner" / "runner.sh"


@app.get("/runner.sh", include_in_schema=False)
async def serve_runner():
    return FileResponse(_RUNNER_PATH, media_type="text/plain")
