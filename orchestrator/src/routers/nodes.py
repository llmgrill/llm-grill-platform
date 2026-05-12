from fastapi import APIRouter, Depends, status

from src.auth import require_api_key
from src.controllers.node_controller import NodeController
from src.schemas import NodeCreate, NodeRead

router = APIRouter(prefix="/nodes", tags=["nodes"])


@router.post(
    "",
    response_model=NodeRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_api_key)],
)
async def register_node(body: NodeCreate):
    return await NodeController.register(body)


@router.get("", response_model=list[NodeRead])
async def list_nodes():
    return await NodeController.list_all()


@router.get("/{node_id}", response_model=NodeRead)
async def get_node(node_id: str):
    return await NodeController.get(node_id)


@router.delete(
    "/{node_id}", response_model=NodeRead, dependencies=[Depends(require_api_key)]
)
async def deregister_node(node_id: str):
    return await NodeController.deregister(node_id)
