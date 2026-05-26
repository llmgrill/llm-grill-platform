"""
Tests for the GET /leaderboard endpoint.

The leaderboard is served from `s3://.../leaderboard.json` (written
incrementally by RunService.complete via storage.update_leaderboard_for).
These tests mock the S3 fetch — the in-memory cache is invalidated before
each test to avoid leakage.
"""

import json

import pytest

from src.services.result_service import ResultService


@pytest.fixture(autouse=True)
def reset_leaderboard_cache():
    """Drop the 60s in-memory cache before and after each test."""
    ResultService.invalidate_leaderboard_cache()
    yield
    ResultService.invalidate_leaderboard_cache()


def _leaderboard_entry(**overrides) -> dict:
    base = {
        "model": "meta-llama/Llama-3-8B",
        "engine": "vllm",
        "gpu_type": "L40S",
        "tokens_per_second_mean": 45.0,
        "total_tokens_per_second": 120.0,
        "requests_per_second": 3.5,
        "e2e_p95_s": 0.80,
        "ttft_p95_s": 0.25,
        "success_rate": 0.99,
        "run_id": "00000000-0000-0000-0000-000000000001",
        "measured_at": "2026-05-20T10:00:00+00:00",
    }
    return {**base, **overrides}


class TestLeaderboard:
    """GET /leaderboard reads the consolidated JSON from S3."""

    async def test_should_return_empty_list_when_no_leaderboard_on_s3(
        self, client, mocker
    ):
        """
        Given: leaderboard.json does not exist on S3 (fetch returns None)
        When:  GET /leaderboard is called
        Then:  200 with []
        """
        # Given
        mocker.patch("src.services.result_service.fetch_leaderboard", return_value=None)

        # When
        resp = await client.get("/leaderboard")

        # Then
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_should_return_entries_from_s3_payload(self, client, mocker):
        """
        Given: leaderboard.json on S3 holds two entries for distinct models
        When:  GET /leaderboard is called
        Then:  Both entries are returned with the same field values
        """
        # Given
        payload = json.dumps(
            [
                _leaderboard_entry(
                    model="mistralai/Mistral-7B-v0.1",
                    total_tokens_per_second=200.0,
                    run_id="00000000-0000-0000-0000-000000000002",
                ),
                _leaderboard_entry(total_tokens_per_second=80.0),
            ]
        ).encode()
        mocker.patch(
            "src.services.result_service.fetch_leaderboard", return_value=payload
        )

        # When
        resp = await client.get("/leaderboard")

        # Then
        assert resp.status_code == 200
        data = resp.json()
        assert {e["model"] for e in data} == {
            "mistralai/Mistral-7B-v0.1",
            "meta-llama/Llama-3-8B",
        }
        assert any(e["total_tokens_per_second"] == pytest.approx(200.0) for e in data)

    async def test_should_serve_from_cache_within_ttl(self, client, mocker):
        """
        Given: A first request that fetched leaderboard.json from S3
        When:  A second request hits within the 60s TTL
        Then:  fetch_leaderboard is only called once (the second hit is cached)
        """
        # Given
        payload = json.dumps([_leaderboard_entry()]).encode()
        fetch_mock = mocker.patch(
            "src.services.result_service.fetch_leaderboard", return_value=payload
        )

        # When
        await client.get("/leaderboard")
        await client.get("/leaderboard")

        # Then
        assert fetch_mock.call_count == 1

    async def test_should_refetch_after_ttl_expires(self, client, mocker):
        """
        Given: A first request cached leaderboard.json
        When:  A second request hits just past the 60s TTL (clock advanced)
        Then:  fetch_leaderboard is called again (cache considered stale)
        """
        # Given
        import src.services.result_service as rs

        payload = json.dumps([_leaderboard_entry()]).encode()
        fetch_mock = mocker.patch(
            "src.services.result_service.fetch_leaderboard", return_value=payload
        )

        # When: first call caches; we then age the cache past the TTL window
        # (cheaper and safer than patching the global time.monotonic, which
        # asyncio also consumes).
        await client.get("/leaderboard")
        assert rs._leaderboard_cache is not None
        cached_at, entries = rs._leaderboard_cache
        rs._leaderboard_cache = (cached_at - rs._LEADERBOARD_TTL_SECONDS - 1, entries)
        await client.get("/leaderboard")

        # Then
        assert fetch_mock.call_count == 2
