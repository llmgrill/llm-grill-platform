import uuid

from fastapi import HTTPException, status

from src.aggregation import aggregate
from src.models import GpuType, Run, RunStatus
from src.repositories.run_repository import RunRepository
from src.schemas import RunCreate
from src.storage import upload_logs, upload_results

_MAX_LOG_BYTES = 5 * 1024 * 1024
_HALF_LOG_BYTES = 2 * 1024 * 1024  # 2 MB head + 2 MB tail (leaves room for marker)

_L40S_THRESHOLD_B = 26


class RunService:
    @staticmethod
    async def get(run_id: uuid.UUID) -> Run | None:
        return await RunRepository.get(run_id)

    @staticmethod
    async def list_all(status: RunStatus | None = None) -> list[Run]:
        return await RunRepository.get_all(status)

    @staticmethod
    def select_gpu(model_size_b: int) -> GpuType:
        if model_size_b < _L40S_THRESHOLD_B:
            return GpuType.L40S
        return GpuType.H100

    @staticmethod
    async def create(body: RunCreate) -> Run:
        run = Run(
            **body.model_dump(),
            gpu_type_required=RunService.select_gpu(body.model_size_b),
        )
        return await RunRepository.create(run)

    @staticmethod
    async def complete(run_id: uuid.UUID, results_jsonl: str) -> Run:
        run = await RunRepository.get(run_id)
        if run is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="run not found")
        if run.status != RunStatus.running:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="run is not running")

        # Upload before committing — if S3 fails, run stays `running` and can be retried.
        results_url = await upload_results(run_id, results_jsonl)
        result = aggregate(results_jsonl, run)
        return await RunRepository.complete_run(run_id, results_url, result)

    @staticmethod
    async def attach_logs(run_id: uuid.UUID, body: bytes) -> Run:
        run = await RunRepository.get(run_id)
        if run is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="run not found")
        if len(body) > _MAX_LOG_BYTES:
            marker = (
                f"\n[... truncated middle {len(body) - 2 * _HALF_LOG_BYTES} bytes ...]\n"
            ).encode()
            body = body[:_HALF_LOG_BYTES] + marker + body[-_HALF_LOG_BYTES:]
        key = await upload_logs(run_id, body)
        await RunRepository.set_logs_url(run_id, key)
        updated = await RunRepository.get(run_id)
        if updated is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail="run not found after log upload"
            )
        return updated

    @staticmethod
    async def fail(run_id: uuid.UUID, error_message: str) -> Run:
        run = await RunRepository.get(run_id)
        if run is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="run not found")
        if run.status not in {RunStatus.running, RunStatus.provisioning}:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="run cannot be failed")
        return await RunRepository.fail_run(run_id, error_message)
