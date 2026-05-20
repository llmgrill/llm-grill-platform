"""Verify every entry in `orchestrator/models.yaml` resolves on HuggingFace.

Marked `integration` because it hits the public HuggingFace API.
Run explicitly with: `pytest -m integration tests/test_models_yaml.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from huggingface_hub import list_repo_files
from huggingface_hub.utils import RepositoryNotFoundError

_MODELS_YAML = Path(__file__).resolve().parents[1] / "models.yaml"


def _load_models() -> list[tuple[str, str | None]]:
    """Return `(model_id, gguf_file)` for each entry in `models.yaml`."""
    data = yaml.safe_load(_MODELS_YAML.read_text())
    return [(entry["model"], entry.get("gguf_file")) for entry in data["models"]]


@pytest.mark.integration
@pytest.mark.parametrize(("model_id", "gguf_file"), _load_models())
def test_model_resolves_on_huggingface(model_id: str, gguf_file: str | None) -> None:
    """Given a model entry in models.yaml,
    when listing its files on HuggingFace,
    then the repo must exist and any declared `gguf_file` must be present.
    """
    try:
        files = set(list_repo_files(model_id))
    except RepositoryNotFoundError:
        pytest.fail(f"HuggingFace repo not found: {model_id}")

    if gguf_file is not None:
        assert gguf_file in files, (
            f"{model_id}: declared gguf_file {gguf_file!r} not in repo "
            f"(available .gguf: {sorted(f for f in files if f.endswith('.gguf'))[:5]})"
        )
