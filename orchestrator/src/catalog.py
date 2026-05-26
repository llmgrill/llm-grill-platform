"""Derive the public model + scenario catalogs published alongside the leaderboard.

The static frontend reads only public JSON from S3; it cannot read models.yaml
or scenarios/*.yaml from the repo. So we derive `models.json` and
`scenarios.json` from those files at bench time and publish them.

Everything here is derived — no editorial field is hand-maintained in
models.yaml (see the agent design discussion). `brand` comes from the HF org,
`params_b` from `size_b`, `quantization` is parsed from the GGUF filename.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from loguru import logger

if TYPE_CHECKING:
    from src.services.bench_service import ModelEntry

# GGUF quant tag, e.g. Q4_K_M, Q5_K_S, Q8_0, IQ4_XS, BF16, F16 in a filename
# like "Qwen2.5-14B-Instruct-Q4_K_M.gguf".
_QUANT_RE = re.compile(r"(IQ\d+[\w]*|Q\d+(?:_[A-Z0-9]+)*|BF16|F16|F32)", re.IGNORECASE)


def _quantization(gguf_file: str | None) -> str | None:
    if not gguf_file:
        return None
    match = _QUANT_RE.search(Path(gguf_file).stem)
    return match.group(0).upper() if match else None


def build_models_catalog(entries: list[ModelEntry]) -> list[dict]:
    """One derived metadata row per (model, engine), keyed by the front on `model`."""
    return [
        {
            "model": e.model,
            "engine": e.engine,
            "brand": e.model.split("/")[0],
            "params_b": e.size_b,
            "quantization": _quantization(e.gguf_file),
            "scenario": e.scenario,
        }
        for e in entries
    ]


def build_scenarios_catalog(root: Path) -> list[dict]:
    """Expose every scenario's load shape (concurrency levels, prompt…).

    Discovers all `scenarios/*.yaml` under `root` so future scenarios surface
    without touching this code, independent of which models reference them.
    The leaderboard's per-model `scenario` path keys back into this catalog.
    """
    scenarios_dir = root / "scenarios"
    if not scenarios_dir.is_dir():
        return []
    catalog: list[dict] = []
    for path in sorted(scenarios_dir.glob("*.yaml")):
        doc = yaml.safe_load(path.read_text())
        if not isinstance(doc, dict):
            # A malformed scenario (top-level list/str/empty) must not break the
            # whole bench submission — skip it and keep publishing the rest.
            logger.warning("Skipping malformed scenario file: {}", path.name)
            continue
        catalog.append(_scenario_summary(f"scenarios/{path.name}", doc))
    return catalog


def _scenario_summary(scenario_path: str, doc: dict) -> dict:
    load = doc.get("load") or {}
    models = doc.get("models") or []
    conversations = doc.get("conversations") or []
    return {
        "path": scenario_path,
        "name": doc.get("name", Path(scenario_path).stem),
        "description": (doc.get("description") or "").strip(),
        "concurrency_levels": load.get("ramp_levels", []),
        "iterations": load.get("iterations"),
        "max_tokens": _first_max_tokens(models),
        "prompt": _first_user_prompt(conversations),
    }


def _first_max_tokens(models: list) -> int | None:
    for model in models:
        if isinstance(model, dict) and "max_tokens" in model:
            return model["max_tokens"]
    return None


def _first_user_prompt(conversations: list[dict]) -> str | None:
    for conv in conversations:
        for turn in conv.get("turns", []):
            if turn.get("role") == "user":
                return turn.get("content")
    return None
