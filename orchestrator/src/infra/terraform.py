import asyncio
import json
import re
import shutil
import uuid
from pathlib import Path

from loguru import logger

from src.config import settings
from src.models import GpuType, Run


class TerraformError(RuntimeError):
    """Base class for terraform-driven provisioning failures."""


class OutOfStockError(TerraformError):
    """Scaleway reports the requested instance SKU has no capacity."""


class ScalewayAuthError(TerraformError):
    """Scaleway credentials are missing or invalid."""


class ScalewayQuotaError(TerraformError):
    """Account quota exceeded for the requested resource."""


_OUT_OF_STOCK_RE = re.compile(r"out of stock", re.IGNORECASE)
_AUTH_RE = re.compile(
    r"(access key cannot be empty|secret key cannot be empty|"
    r"invalid (?:access|secret) key|authentication failed|unauthorized)",
    re.IGNORECASE,
)
_QUOTA_RE = re.compile(r"(quota|limit).*(exceed|reach)", re.IGNORECASE)


def _classify(stderr: str) -> TerraformError:
    if _OUT_OF_STOCK_RE.search(stderr):
        return OutOfStockError(stderr.strip())
    if _AUTH_RE.search(stderr):
        return ScalewayAuthError(stderr.strip())
    if _QUOTA_RE.search(stderr):
        return ScalewayQuotaError(stderr.strip())
    return TerraformError(stderr.strip())


parent_dir = Path(__file__).resolve().parents[2]
_TERRAFORM_DIR = parent_dir / "terraform"
_WORKSPACES_DIR = _TERRAFORM_DIR / "workspaces"
_RUNNER_SCRIPT = parent_dir / "runner.sh"

_INSTANCE_TYPE = {
    GpuType.L40S: "L40S-1-48G",
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
        raise _classify(stderr.decode())
    return stdout.decode()


async def provision_node(run: Run) -> tuple[str, str]:
    run_id = run.id
    gpu_type = run.gpu_type_required
    workspace = _workspace(run_id)
    workspace.mkdir(parents=True, exist_ok=True)

    for f in _TERRAFORM_DIR.glob("*.tf"):
        shutil.copy(f, workspace)
    shutil.copy(_TERRAFORM_DIR / "cloud-init.tpl.yaml", workspace)
    shutil.copy(_RUNNER_SCRIPT, workspace)

    ssh_keys = [k.strip() for k in settings.ssh_public_keys.split(",") if k.strip()]
    ssh_keys_hcl = "[" + ", ".join(f'"{k}"' for k in ssh_keys) + "]"

    scenario_file = (parent_dir / run.scenario_path).resolve()
    if not scenario_file.is_file():
        raise TerraformError(f"scenario file not found: {scenario_file}")
    scenario_content = scenario_file.read_text().replace("${MODEL}", run.model)

    # Non-secret vars written to file; secrets passed via -var flags to avoid disk exposure
    var_file = workspace / "terraform.tfvars"
    var_file.write_text(
        f'run_id          = "{run_id}"\n'
        f'gpu_type        = "{gpu_type.value}"\n'
        f'instance_type   = "{_INSTANCE_TYPE[gpu_type]}"\n'
        f'orchestrator_url = "{settings.orchestrator_url}"\n'
        f'gpu_zone        = "{settings.gpu_zone}"\n'
        f"ssh_public_keys = {ssh_keys_hcl}\n"
        f'model           = "{run.model}"\n'
        f'engine          = "{run.engine.value}"\n'
        f'scenario_path   = "{run.scenario_path}"\n'
        f'gguf_file       = "{run.gguf_file or ""}"\n'
        f"scenario_content = <<EOT_SCENARIO\n{scenario_content}\nEOT_SCENARIO\n"
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
    logger.info("provisioned node {} ({}) for run {}", instance_id, public_ip, run_id)
    return instance_id, public_ip


async def destroy_node(run_id: uuid.UUID) -> None:
    workspace = _workspace(run_id)
    if not workspace.exists():
        logger.warning("workspace {} not found, skipping destroy", workspace)
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
    logger.info("destroyed node for run {}", run_id)
