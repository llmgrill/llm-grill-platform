"""
Tests for terraform helpers — provision_node and destroy_node.

All subprocess calls are mocked. No real Terraform binary or workspace needed.
"""

import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.infra.terraform import destroy_node, provision_node
from src.models import Engine, GpuType, Run


def _fake_run(run_id: uuid.UUID, gpu_type: GpuType) -> Run:
    return Run(
        id=run_id,
        model="meta-llama/Llama-3.1-8B-Instruct",
        model_size_b=8,
        engine=Engine.vllm,
        gpu_type_required=gpu_type,
        gpu_count=1,
        scenario_path="scenarios/basic_8b.yaml",
    )


def _fake_terraform(outputs: dict | None = None):
    """Return an async mock for _terraform that yields JSON output on 'output' calls."""
    outputs = outputs or {
        "instance_id": {"value": "scw-abc123"},
        "public_ip": {"value": "1.2.3.4"},
    }

    async def _inner(workspace: Path, *args: str) -> str:
        if args and args[0] == "output":
            return json.dumps(outputs)
        return ""

    return _inner


class TestProvisionNode:
    """Tests for provision_node — copy Terraform files, init, apply, capture outputs."""

    async def test_should_return_instance_id_and_public_ip(self, tmp_path, mocker):
        """
        Should run terraform init+apply+output and parse instance_id and public_ip.

        Given: A mocked _terraform that returns fake instance outputs
        When: provision_node is called
        Then: Returns (instance_id, public_ip) from terraform output
        """
        # Given
        mocker.patch("src.infra.terraform._TERRAFORM_DIR", tmp_path)
        mocker.patch("src.infra.terraform._WORKSPACES_DIR", tmp_path / "workspaces")
        mocker.patch("src.infra.terraform._SCENARIOS_ROOT", tmp_path)
        mocker.patch("src.infra.terraform._RUNNER_SCRIPT", tmp_path / "runner.sh")
        mocker.patch("src.infra.terraform._REQUIREMENTS", tmp_path / "requirements.txt")
        (tmp_path).mkdir(exist_ok=True)
        (tmp_path / "cloud-init.tpl.yaml").write_text("cloud-init")
        (tmp_path / "runner.sh").write_text("#!/bin/sh")
        (tmp_path / "requirements.txt").write_text("huggingface_hub==1.16.1")
        (tmp_path / "scenarios").mkdir(exist_ok=True)
        (tmp_path / "scenarios" / "basic_8b.yaml").write_text("model: ${MODEL}")
        mocker.patch("src.infra.terraform._terraform", side_effect=_fake_terraform())
        run_id = uuid.uuid4()

        # When
        instance_id, public_ip = await provision_node(_fake_run(run_id, GpuType.L40S))

        # Then
        assert instance_id == "scw-abc123"
        assert public_ip == "1.2.3.4"

    async def test_should_raise_when_terraform_fails(self, tmp_path, mocker):
        """
        Should propagate RuntimeError when terraform apply exits non-zero.

        Given: _terraform raises RuntimeError on apply
        When: provision_node is called
        Then: RuntimeError is raised
        """
        # Given
        mocker.patch("src.infra.terraform._TERRAFORM_DIR", tmp_path)
        mocker.patch("src.infra.terraform._WORKSPACES_DIR", tmp_path / "workspaces")
        mocker.patch("src.infra.terraform._SCENARIOS_ROOT", tmp_path)
        mocker.patch("src.infra.terraform._RUNNER_SCRIPT", tmp_path / "runner.sh")
        mocker.patch("src.infra.terraform._REQUIREMENTS", tmp_path / "requirements.txt")
        (tmp_path / "cloud-init.tpl.yaml").write_text("cloud-init")
        (tmp_path / "runner.sh").write_text("#!/bin/sh")
        (tmp_path / "requirements.txt").write_text("huggingface_hub==1.16.1")
        (tmp_path / "scenarios").mkdir(exist_ok=True)
        (tmp_path / "scenarios" / "basic_8b.yaml").write_text("model: ${MODEL}")

        async def _fail(workspace, *args):
            raise RuntimeError("terraform apply failed")

        mocker.patch("src.infra.terraform._terraform", side_effect=_fail)
        run_id = uuid.uuid4()

        # When / Then
        with pytest.raises(RuntimeError, match="terraform apply failed"):
            await provision_node(_fake_run(run_id, GpuType.L40S))


class TestDestroyNode:
    """Tests for destroy_node — run terraform destroy and remove the workspace."""

    async def test_should_run_destroy_and_remove_workspace(self, tmp_path, mocker):
        """
        Should call terraform destroy and delete the workspace directory.

        Given: A workspace directory exists for the run
        When: destroy_node is called
        Then: terraform destroy is called and workspace is removed
        """
        # Given
        run_id = uuid.uuid4()
        workspace = tmp_path / str(run_id)
        workspace.mkdir()
        mocker.patch("src.infra.terraform._WORKSPACES_DIR", tmp_path)

        mock_tf = AsyncMock(return_value="")
        mocker.patch("src.infra.terraform._terraform", mock_tf)

        # When
        await destroy_node(run_id)

        # Then
        mock_tf.assert_awaited_once()
        assert not workspace.exists()

    async def test_should_skip_destroy_when_workspace_missing(self, tmp_path, mocker):
        """
        Should log a warning and return early when workspace directory does not exist.

        Given: No workspace directory for the run
        When: destroy_node is called
        Then: terraform is not called, no exception raised
        """
        # Given
        mocker.patch("src.infra.terraform._WORKSPACES_DIR", tmp_path)
        mock_tf = AsyncMock(return_value="")
        mocker.patch("src.infra.terraform._terraform", mock_tf)
        run_id = uuid.uuid4()

        # When
        await destroy_node(run_id)

        # Then
        mock_tf.assert_not_awaited()
