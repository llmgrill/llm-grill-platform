import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi import status as http_status
from fastapi.responses import PlainTextResponse

from src.auth import require_api_key
from src.controllers.run_controller import RunController
from src.models import RunStatus
from src.repositories.run_repository import RunRepository
from src.schemas import RunComplete, RunCreate, RunFail, RunRead
from src.storage import fetch_logs

router = APIRouter(prefix="/runs", tags=["runs"])


@router.post(
    "",
    response_model=RunRead,
    status_code=http_status.HTTP_201_CREATED,
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


@router.post(
    "/{run_id}/logs",
    status_code=http_status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_api_key)],
)
async def attach_run_logs(run_id: uuid.UUID, request: Request):
    body = await request.body()
    await RunController.attach_logs(run_id, body)


@router.get("/{run_id}/logs", response_class=PlainTextResponse)
async def get_run_logs(run_id: uuid.UUID):
    run = await RunRepository.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    content = await fetch_logs(run)
    if content is None:
        raise HTTPException(status_code=404, detail="no logs uploaded for this run")
    return content.decode("utf-8", errors="replace")
