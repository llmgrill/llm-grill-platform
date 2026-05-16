import uuid

from sqlalchemy import and_, func, select

from src import db
from src.models import Result


class ResultRepository:
    @staticmethod
    async def get_all() -> list[Result]:
        async with db.AsyncSessionLocal() as session:
            result = await session.execute(
                select(Result).order_by(Result.created_at.desc())
            )
            return list(result.scalars().all())

    @staticmethod
    async def get_by_run(run_id: uuid.UUID) -> Result | None:
        async with db.AsyncSessionLocal() as session:
            result = await session.execute(
                select(Result).where(Result.run_id == run_id)
            )
            return result.scalar_one_or_none()

    @staticmethod
    async def get_latest_per_combination() -> list[Result]:
        async with db.AsyncSessionLocal() as session:
            subq = (
                select(
                    Result.model,
                    Result.engine,
                    Result.gpu_type,
                    func.max(Result.created_at).label("latest"),
                )
                .group_by(Result.model, Result.engine, Result.gpu_type)
                .subquery()
            )
            stmt = (
                select(Result)
                .join(
                    subq,
                    and_(
                        Result.model == subq.c.model,
                        Result.engine == subq.c.engine,
                        Result.gpu_type == subq.c.gpu_type,
                        Result.created_at == subq.c.latest,
                    ),
                )
                .order_by(Result.total_tokens_per_second.desc())
            )
            rows = (await session.execute(stmt)).scalars().all()
            return list(rows)
