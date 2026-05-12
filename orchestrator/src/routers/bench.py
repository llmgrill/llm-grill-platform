from fastapi import APIRouter, Depends

from src.auth import require_api_key
from src.services import bench_service

router = APIRouter(prefix="/bench", tags=["bench"])


@router.post("", dependencies=[Depends(require_api_key)])
async def submit_bench(force: bool = False, model: str | None = None):
    """
    Enqueue benchmark runs for all models in models.yaml.
    Skips models that already have a completed run unless force=true.
    Optionally restrict to a single model with ?model=<partial HF ID>.
    """
    return await bench_service.submit(force=force, model_filter=model)


@router.get("/status")
async def bench_status():
    """
    Return run counts by status. CI polls this until active=0.
    """
    return await bench_service.bench_status()
