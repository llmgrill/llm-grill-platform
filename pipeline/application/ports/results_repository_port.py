"""Port for reading and writing benchmark results."""

from __future__ import annotations

from typing import Any, Protocol


class ResultsRepositoryPort(Protocol):
    """Read/write access to benchmark JSONL results and aggregated JSON."""

    def has_result(self, date: str, slug: str, backend: str) -> bool: ...

    def write_jsonl(
        self, date: str, slug: str, backend: str, rows: list[dict[str, Any]]
    ) -> None: ...

    def read_jsonl(
        self, date: str, slug: str, backend: str
    ) -> list[dict[str, Any]]: ...

    def list_runs(self) -> list[tuple[str, str, str]]:
        """Return all (date, slug, backend) triples present in storage."""
        ...

    def write_summary(self, summary: dict[str, Any]) -> None: ...

    def write_aggregated_leaderboard(self, data: list[dict[str, Any]]) -> None: ...

    def write_aggregated_model(self, slug: str, data: dict[str, Any]) -> None: ...

    def write_aggregated_history(self, data: dict[str, Any]) -> None: ...
