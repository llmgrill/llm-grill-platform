"""Tests for catalog derivation — models.json and scenarios.json builders."""

from typing import Literal

from src.catalog import build_models_catalog, build_scenarios_catalog
from src.services.bench_service import ModelEntry


def _entry(
    model: str,
    engine: Literal["vllm", "llamacpp"] = "vllm",
    size_b: int = 8,
    gguf_file: str | None = None,
) -> ModelEntry:
    return ModelEntry(model=model, engine=engine, size_b=size_b, gguf_file=gguf_file)


class TestBuildModelsCatalog:
    """build_models_catalog() derives editorial metadata, no hand-maintained fields."""

    def test_should_derive_brand_and_params_from_id_and_size(self):
        """
        Given: a vLLM entry "Qwen/Qwen2.5-14B-Instruct" of size 14
        When: the models catalog is built
        Then: brand is the HF org, params_b is size_b, quantization is null
        """
        catalog = build_models_catalog([_entry("Qwen/Qwen2.5-14B-Instruct", size_b=14)])

        assert catalog == [
            {
                "model": "Qwen/Qwen2.5-14B-Instruct",
                "engine": "vllm",
                "brand": "Qwen",
                "params_b": 14,
                "quantization": None,
                "scenario": "scenarios/ramp.yaml",
            }
        ]

    def test_should_parse_quantization_from_gguf_filename(self):
        """
        Given: a llamacpp entry with a Q4_K_M GGUF file
        When: the models catalog is built
        Then: quantization is parsed from the filename
        """
        catalog = build_models_catalog(
            [
                _entry(
                    "bartowski/Qwen2.5-14B-Instruct-GGUF",
                    engine="llamacpp",
                    gguf_file="Qwen2.5-14B-Instruct-Q4_K_M.gguf",
                )
            ]
        )

        assert catalog[0]["quantization"] == "Q4_K_M"


class TestBuildScenariosCatalog:
    """build_scenarios_catalog() summarizes referenced scenario YAMLs."""

    def test_should_summarize_scenario_load_shape(self, tmp_path):
        """
        Given: a scenarios/ramp.yaml under the root
        When: the scenarios catalog is built
        Then: a summary is returned with the load shape and first user prompt
        """
        (tmp_path / "scenarios").mkdir()
        (tmp_path / "scenarios" / "ramp.yaml").write_text(
            "name: ramp\n"
            "description: |\n  Ramp test.\n"
            "models:\n  - name: m\n    max_tokens: 256\n"
            "conversations:\n  - name: c\n    turns:\n"
            "      - role: user\n        content: Hello?\n"
            "load:\n  ramp_levels: [1, 4, 64]\n  iterations: 2\n"
        )

        catalog = build_scenarios_catalog(tmp_path)

        assert catalog == [
            {
                "path": "scenarios/ramp.yaml",
                "name": "ramp",
                "description": "Ramp test.",
                "concurrency_levels": [1, 4, 64],
                "iterations": 2,
                "max_tokens": 256,
                "prompt": "Hello?",
            }
        ]

    def test_should_discover_all_scenarios_sorted(self, tmp_path):
        """
        Given: two scenario files in the scenarios/ directory
        When: the scenarios catalog is built
        Then: both are discovered, sorted by filename, regardless of model refs
        """
        (tmp_path / "scenarios").mkdir()
        (tmp_path / "scenarios" / "ramp.yaml").write_text("name: ramp\n")
        (tmp_path / "scenarios" / "burst.yaml").write_text("name: burst\n")

        catalog = build_scenarios_catalog(tmp_path)

        assert [s["name"] for s in catalog] == ["burst", "ramp"]

    def test_should_return_empty_when_no_scenarios_dir(self, tmp_path):
        """
        Given: a root with no scenarios/ directory
        When: the scenarios catalog is built
        Then: an empty list is returned rather than raising
        """
        assert build_scenarios_catalog(tmp_path) == []

    def test_should_skip_malformed_scenario_keep_valid_ones(self, tmp_path):
        """
        Given: one valid scenario and one with a top-level list (not a mapping)
        When: the scenarios catalog is built
        Then: the malformed file is skipped, the valid one still published
        """
        (tmp_path / "scenarios").mkdir()
        (tmp_path / "scenarios" / "ramp.yaml").write_text("name: ramp\n")
        (tmp_path / "scenarios" / "broken.yaml").write_text("- just\n- a\n- list\n")

        catalog = build_scenarios_catalog(tmp_path)

        assert [s["name"] for s in catalog] == ["ramp"]
