import json
import time
import uuid

from fastapi import HTTPException, status

from src.models import Result
from src.repositories.result_repository import ResultRepository
from src.repositories.run_repository import RunRepository
from src.schemas import LeaderboardEntry
from src.storage import fetch_leaderboard, presigned_url

_LEADERBOARD_TTL_SECONDS = 60

# (cached_at_monotonic, entries) — None until first hit.
_leaderboard_cache: tuple[float, list[LeaderboardEntry]] | None = None


class ResultService:
    @staticmethod
    async def get_by_run(run_id: uuid.UUID) -> Result | None:
        return await ResultRepository.get_by_run(run_id)

    @staticmethod
    async def get_download_url(run_id: uuid.UUID) -> str:
        run = await RunRepository.get(run_id)
        if run is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="run not found")
        return await presigned_url(run)

    @staticmethod
    async def get_leaderboard() -> list[LeaderboardEntry]:
        """Serve leaderboard.json from S3 with a 60s in-memory TTL cache."""
        global _leaderboard_cache
        now = time.monotonic()
        if (
            _leaderboard_cache is not None
            and now - _leaderboard_cache[0] < _LEADERBOARD_TTL_SECONDS
        ):
            return _leaderboard_cache[1]

        blob = await fetch_leaderboard()
        raw = json.loads(blob) if blob else []
        entries = [LeaderboardEntry.model_validate(e) for e in raw]
        _leaderboard_cache = (now, entries)
        return entries

    @staticmethod
    def invalidate_leaderboard_cache() -> None:
        """Drop the cache — useful in tests and after manual S3 mutations."""
        global _leaderboard_cache
        _leaderboard_cache = None
