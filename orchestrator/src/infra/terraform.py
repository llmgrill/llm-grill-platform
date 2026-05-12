import asyncio
import json
import logging
import shutil
import uuid
from pathlib import Path

from src.config import settings
from src.models import GpuType

logger = logging.getLogger(__name__)

_TERRAFORM_DIR = Path(__file__).resolve().parents[3] / "terraform"
_WORKSPACES_DIR = _TERRAFORM_DIR / "workspaces"

_INSTANCE_TYPE = {
    GpuType.L40S: "GPU-L40S-1-80G",
    GpuType.H100: "H100-1-80G",
}


def _workspace(run_id: uuid.UUID) -> Path:
    return _WORKSPACES_DIR / str(run_id)


async def _terraform(workspace: Path, *args: str) -> str:
    cmd = ["terraform", f"-chdir={workspace}", *args]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"terraform {' '.join(args)} failed:\n{stderr.decode()}")
    return stdout.decode()


async def provision_node(run_id: uuid.UUID, gpu_type: GpuType) -> tuple[str, str]:
    workspace = _workspace(run_id)
    workspace.mkdir(parents=True, exist_ok=True)

    for f in _TERRAFORM_DIR.glob("*.tf"):
        shutil.copy(f, workspace)
    shutil.copy(_TERRAFORM_DIR / "cloud-init.tpl.yaml", workspace)

    # Non-secret vars written to file; secrets passed via -var flags to avoid disk exposure
    var_file = workspace / "terraform.tfvars"
    var_file.write_text(
        f'run_id          = "{run_id}"\n'
        f'gpu_type        = "{gpu_type.value}"\n'
        f'instance_type   = "{_INSTANCE_TYPE[gpu_type]}"\n'
        f'orchestrator_url = "{settings.orchestrator_url}"\n'
        f'gpu_zone        = "{settings.gpu_zone}"\n'
    )

    secret_vars = [
        "-var",
        f"hf_token={settings.hf_token}",
        "-var",
        f"orchestrator_api_key={settings.api_key}",
    ]

    await _terraform(workspace, "init", "-input=false")
    await _terraform(workspace, "apply", "-auto-approve", "-input=false", *secret_vars)

    output = await _terraform(workspace, "output", "-json")
    out = json.loads(output)
    instance_id: str = out["instance_id"]["value"]
    public_ip: str = out["public_ip"]["value"]
    logger.info("provisioned node %s (%s) for run %s", instance_id, public_ip, run_id)
    return instance_id, public_ip


async def destroy_node(run_id: uuid.UUID) -> None:
    workspace = _workspace(run_id)
    if not workspace.exists():
        logger.warning("workspace %s not found, skipping destroy", workspace)
        return
    secret_vars = [
        "-var",
        f"hf_token={settings.hf_token}",
        "-var",
        f"orchestrator_api_key={settings.api_key}",
    ]
    await _terraform(
        workspace, "destroy", "-auto-approve", "-input=false", *secret_vars
    )
    shutil.rmtree(workspace)
    logger.info("destroyed node for run %s", run_id)
