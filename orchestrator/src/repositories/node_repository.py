import uuid

from sqlalchemy import select

from src import db
from src.models import GpuType, Node, NodeStatus, Run, RunStatus


class NodeRepository:
    @staticmethod
    async def get(node_id: str) -> Node | None:
        async with db.AsyncSessionLocal() as session:
            return await session.get(Node, node_id)

    @staticmethod
    async def get_all() -> list[Node]:
        async with db.AsyncSessionLocal() as session:
            result = await session.execute(select(Node).order_by(Node.id))
            return list(result.scalars().all())

    @staticmethod
    async def get_by_run(run_id: uuid.UUID) -> Node | None:
        async with db.AsyncSessionLocal() as session:
            result = await session.execute(
                select(Node).where(Node.current_run_id == run_id)
            )
            return result.scalar_one_or_none()

    @staticmethod
    async def create(node: Node) -> Node:
        async with db.AsyncSessionLocal() as session:
            session.add(node)
            await session.commit()
            await session.refresh(node)
            return node

    @staticmethod
    async def save(node: Node) -> Node:
        async with db.AsyncSessionLocal() as session:
            node = await session.merge(node)
            await session.commit()
            await session.refresh(node)
            return node

    @staticmethod
    async def create_provisioning(run_id: uuid.UUID, gpu_type: GpuType) -> Node:
        """Insert or reset a `provisioning` node row for this run.

        Idempotent so retries (e.g. after `out of stock` re-queue) don't fail
        on a duplicate primary key when the previous attempt left a `down`
        row behind.
        """
        node_id = f"node-{run_id}"
        async with db.AsyncSessionLocal() as session:
            node = await session.get(Node, node_id)
            if node is None:
                node = Node(
                    id=node_id,
                    gpu_type=gpu_type,
                    status=NodeStatus.provisioning,
                    current_run_id=run_id,
                )
                session.add(node)
            else:
                node.gpu_type = gpu_type
                node.status = NodeStatus.provisioning
                node.ip_address = None
                node.current_run_id = run_id
            await session.commit()
            await session.refresh(node)
            return node

    @staticmethod
    async def set_busy(run_id: uuid.UUID, instance_id: str, public_ip: str) -> None:
        async with db.AsyncSessionLocal() as session:
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
        async with db.AsyncSessionLocal() as session:
            result = await session.execute(
                select(Node.current_run_id)
                .join(Run, Run.id == Node.current_run_id)
                .where(Node.status == NodeStatus.busy)
                .where(Run.status.in_([RunStatus.done, RunStatus.failed]))
            )
            return [row[0] for row in result.all() if row[0] is not None]

    @staticmethod
    async def set_down_by_run(run_id: uuid.UUID) -> None:
        async with db.AsyncSessionLocal() as session:
            result = await session.execute(
                select(Node).where(Node.current_run_id == run_id)
            )
            node = result.scalar_one_or_none()
            if node:
                node.status = NodeStatus.down
                await session.commit()
