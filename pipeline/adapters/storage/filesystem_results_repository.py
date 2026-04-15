"""Filesystem-backed results repository + in-memory variant for tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class FilesystemResultsRepository:
    """Reads/writes the ``results/`` layout on disk (ADR 001c)."""

    def __init__(self, root: Path, read_roots: list[Path] | None = None) -> None:
        self._root = Path(root)
        # Additional read-only roots (e.g. ``results/fixtures/``).
        self._read_roots = [self._root, *[Path(p) for p in (read_roots or [])]]

    # ----- raw JSONL ---------------------------------------------------
    def _path(self, date: str, slug: str, backend: str) -> Path:
        return self._root / date / slug / f"{backend}.jsonl"

    def has_result(self, date: str, slug: str, backend: str) -> bool:
        for root in self._read_roots:
            if (root / date / slug / f"{backend}.jsonl").exists():
                return True
        return False

    def write_jsonl(
        self, date: str, slug: str, backend: str, rows: list[dict[str, Any]]
    ) -> None:
        p = self._path(date, slug, backend)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, separators=(",", ":")) + "\n")

    def read_jsonl(self, date: str, slug: str, backend: str) -> list[dict[str, Any]]:
        for root in self._read_roots:
            p = root / date / slug / f"{backend}.jsonl"
            if p.exists():
                with p.open("r", encoding="utf-8") as f:
                    return [json.loads(line) for line in f if line.strip()]
        return []

    def list_runs(self) -> list[tuple[str, str, str]]:
        out: set[tuple[str, str, str]] = set()
        for root in self._read_roots:
            if not root.exists():
                continue
            for date_dir in root.iterdir():
                if not date_dir.is_dir() or date_dir.name in {"aggregated"}:
                    continue
                # Skip the aggregated directory; fixtures/ sits at a different depth.
                if date_dir.name == "fixtures":
                    continue
                for slug_dir in date_dir.iterdir():
                    if not slug_dir.is_dir():
                        continue
                    for file in slug_dir.glob("*.jsonl"):
                        out.add((date_dir.name, slug_dir.name, file.stem))
        return sorted(out)

    # ----- aggregated outputs -----------------------------------------
    def _agg_dir(self) -> Path:
        d = self._root / "aggregated"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def write_summary(self, summary: dict[str, Any]) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        (self._root / "summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
        )

    def write_aggregated_leaderboard(self, data: list[dict[str, Any]]) -> None:
        (self._agg_dir() / "leaderboard.json").write_text(
            json.dumps(data, indent=2, sort_keys=True), encoding="utf-8"
        )

    def write_aggregated_model(self, slug: str, data: dict[str, Any]) -> None:
        models = self._agg_dir() / "models"
        models.mkdir(parents=True, exist_ok=True)
        (models / f"{slug}.json").write_text(
            json.dumps(data, indent=2, sort_keys=True), encoding="utf-8"
        )

    def write_aggregated_history(self, data: dict[str, Any]) -> None:
        (self._agg_dir() / "history.json").write_text(
            json.dumps(data, indent=2, sort_keys=True), encoding="utf-8"
        )


class InMemoryResultsRepository:
    """Test double with the same contract."""

    def __init__(self) -> None:
        self.runs: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        self.summary: dict[str, Any] | None = None
        self.leaderboard: list[dict[str, Any]] | None = None
        self.models: dict[str, dict[str, Any]] = {}
        self.history: dict[str, Any] | None = None

    def has_result(self, date: str, slug: str, backend: str) -> bool:
        return (date, slug, backend) in self.runs

    def write_jsonl(
        self, date: str, slug: str, backend: str, rows: list[dict[str, Any]]
    ) -> None:
        self.runs[(date, slug, backend)] = list(rows)

    def read_jsonl(self, date: str, slug: str, backend: str) -> list[dict[str, Any]]:
        return list(self.runs.get((date, slug, backend), []))

    def list_runs(self) -> list[tuple[str, str, str]]:
        return sorted(self.runs.keys())

    def write_summary(self, summary: dict[str, Any]) -> None:
        self.summary = summary

    def write_aggregated_leaderboard(self, data: list[dict[str, Any]]) -> None:
        self.leaderboard = data

    def write_aggregated_model(self, slug: str, data: dict[str, Any]) -> None:
        self.models[slug] = data

    def write_aggregated_history(self, data: dict[str, Any]) -> None:
        self.history = data
