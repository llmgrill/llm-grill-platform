import uuid

from sqlalchemy import select

import src.db as _db
from src.models import GpuType, Node, NodeStatus, Run, RunStatus


class NodeRepository:
    @staticmethod
    async def get(node_id: str) -> Node | None:
        async with _db.AsyncSessionLocal() as session:
            return await session.get(Node, node_id)

    @staticmethod
    async def get_all() -> list[Node]:
        async with _db.AsyncSessionLocal() as session:
            result = await session.execute(select(Node).order_by(Node.id))
            return list(result.scalars().all())

    @staticmethod
    async def get_by_run(run_id: uuid.UUID) -> Node | None:
        async with _db.AsyncSessionLocal() as session:
            result = await session.execute(
                select(Node).where(Node.current_run_id == run_id)
            )
            return result.scalar_one_or_none()

    @staticmethod
    async def create(node: Node) -> Node:
        async with _db.AsyncSessionLocal() as session:
            session.add(node)
            await session.commit()
            await session.refresh(node)
            return node

    @staticmethod
    async def save(node: Node) -> Node:
        async with _db.AsyncSessionLocal() as session:
            node = await session.merge(node)
            await session.commit()
            await session.refresh(node)
            return node

    @staticmethod
    async def create_provisioning(run_id: uuid.UUID, gpu_type: GpuType) -> Node:
        node = Node(
            id=f"node-{run_id}",
            gpu_type=gpu_type,
            status=NodeStatus.provisioning,
            current_run_id=run_id,
        )
        async with _db.AsyncSessionLocal() as session:
            session.add(node)
            await session.commit()
            await session.refresh(node)
            return node

    @staticmethod
    async def set_busy(run_id: uuid.UUID, instance_id: str, public_ip: str) -> None:
        async with _db.AsyncSessionLocal() as session:
            result = await session.execute(
                select(Node).where(Node.current_run_id == run_id)
            )
            node = result.scalar_one()
            node.id = instance_id
            node.ip_address = public_ip
            node.status = NodeStatus.busy
            await session.commit()

    @staticmethod
    async def get_leaked() -> list[uuid.UUID]:
        """Return run IDs of nodes still busy whose run is done or failed."""
        async with _db.AsyncSessionLocal() as session:
            result = await session.execute(
                select(Node.current_run_id)
                .join(Run, Run.id == Node.current_run_id)
                .where(Node.status == NodeStatus.busy)
                .where(Run.status.in_([RunStatus.done, RunStatus.failed]))
            )
            return [row[0] for row in result.all() if row[0] is not None]

    @staticmethod
    async def set_down_by_run(run_id: uuid.UUID) -> None:
        async with _db.AsyncSessionLocal() as session:
            result = await session.execute(
                select(Node).where(Node.current_run_id == run_id)
            )
            node = result.scalar_one_or_none()
            if node:
                node.status = NodeStatus.down
                await session.commit()
