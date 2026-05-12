import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status

from src.auth import require_api_key
from src.controllers.run_controller import RunController
from src.models import RunStatus
from src.schemas import RunComplete, RunCreate, RunFail, RunRead

router = APIRouter(prefix="/runs", tags=["runs"])


@router.post(
    "",
    response_model=RunRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_api_key)],
)
async def create_run(body: RunCreate):
    return await RunController.create(body)


@router.get("", response_model=list[RunRead])
async def list_runs(status: RunStatus | None = Query(None)):
    return await RunController.list_all(status)


@router.get("/{run_id}", response_model=RunRead)
async def get_run(run_id: uuid.UUID):
    return await RunController.get(run_id)


@router.post(
    "/{run_id}/complete",
    response_model=RunRead,
    dependencies=[Depends(require_api_key)],
)
async def complete_run(
    run_id: uuid.UUID, body: RunComplete, background_tasks: BackgroundTasks
):
    return await RunController.complete(run_id, body, background_tasks)


@router.post(
    "/{run_id}/fail", response_model=RunRead, dependencies=[Depends(require_api_key)]
)
async def fail_run(run_id: uuid.UUID, body: RunFail, background_tasks: BackgroundTasks):
    return await RunController.fail(run_id, body, background_tasks)
