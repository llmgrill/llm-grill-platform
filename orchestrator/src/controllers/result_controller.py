import uuid

from fastapi import HTTPException, status

from src.schemas import LeaderboardEntry, ResultRead
from src.services.result_service import ResultService


class ResultController:
    @staticmethod
    async def get(run_id: uuid.UUID) -> ResultRead:
        result = await ResultService.get_by_run(run_id)
        if result is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="result not found")
        return ResultRead.model_validate(result)

    @staticmethod
    async def download(run_id: uuid.UUID) -> dict:
        result = await ResultService.get_by_run(run_id)
        if result is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="result not found")
        url = await ResultService.get_download_url(run_id)
        return {"url": url}

    @staticmethod
    async def leaderboard() -> list[LeaderboardEntry]:
        return await ResultService.get_leaderboard()
