from __future__ import annotations

from pipeline.application.services.sweep_service import SweepService


class _FakeSweeper:
    def __init__(
        self, orphans: list[str], destroy_failures: set[str] | None = None
    ) -> None:
        self._orphans = orphans
        self._destroy_failures = destroy_failures or set()
        self.destroyed: list[str] = []

    def list_orphans(self, prefix: str, max_age_hours: float) -> list[str]:
        return list(self._orphans)

    def destroy(self, instance_id: str) -> None:
        if instance_id in self._destroy_failures:
            raise RuntimeError("destroy failed")
        self.destroyed.append(instance_id)


def test_run_given_no_orphans_when_swept_then_exit_code_zero():
    # Given
    service = SweepService(_FakeSweeper([]))
    # When
    report = service.run()
    # Then
    assert report.orphans_found == []
    assert report.exit_code == 0


def test_run_given_orphans_when_swept_then_destroyed_and_non_zero_exit():
    # Given
    sweeper = _FakeSweeper(["i-1", "i-2"])
    service = SweepService(sweeper)
    # When
    report = service.run()
    # Then
    assert sweeper.destroyed == ["i-1", "i-2"]
    assert report.exit_code == 1


def test_run_given_destroy_failure_when_swept_then_failure_recorded_and_non_zero_exit():
    # Given
    sweeper = _FakeSweeper(["i-1", "i-2"], destroy_failures={"i-1"})
    service = SweepService(sweeper)
    # When
    report = service.run()
    # Then
    assert sweeper.destroyed == ["i-2"]
    assert [f[0] for f in report.failed] == ["i-1"]
    assert report.exit_code == 1
