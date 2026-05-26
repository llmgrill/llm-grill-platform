import uuid

from fastapi import APIRouter

from src.controllers.result_controller import ResultController
from src.schemas import ResultRead

router = APIRouter(prefix="/results", tags=["results"])


@router.get("/{run_id}", response_model=ResultRead)
async def get_result(run_id: uuid.UUID):
    return await ResultController.get(run_id)


@router.get("/{run_id}/download")
async def download_result(run_id: uuid.UUID):
    return await ResultController.download(run_id)
