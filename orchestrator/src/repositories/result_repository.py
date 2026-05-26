import uuid

from sqlalchemy import select

from src import db
from src.models import Result


class ResultRepository:
    @staticmethod
    async def get_by_run(run_id: uuid.UUID) -> Result | None:
        async with db.AsyncSessionLocal() as session:
            result = await session.execute(
                select(Result).where(Result.run_id == run_id)
            )
            return result.scalar_one_or_none()
