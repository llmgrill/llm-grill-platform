"""
Tests for src.storage — model/engine-keyed S3 layout.

Covers the helpers that drive cross-cycle deduplication:
upload_results (+ latest.jsonl copy), upload_meta, head_latest_meta,
and presigned_url. All boto3 calls are patched; no Scaleway credentials needed.
"""

import json
import uuid

import pytest
from botocore.exceptions import ClientError

from src.models import Engine, GpuType, Result, Run, RunStatus
from src.storage import (
    fetch_latest_results,
    fetch_leaderboard,
    fetch_logs,
    head_latest_meta,
    list_completed,
    presigned_logs_url,
    presigned_url,
    update_leaderboard_for,
    upload_leaderboard,
    upload_logs,
    upload_meta,
    upload_models_catalog,
    upload_results,
    upload_scenarios_catalog,
)

_MODEL = "meta-llama/Llama-3.1-8B-Instruct"
_SLUG = "meta-llama__Llama-3.1-8B-Instruct"


def _body(data: bytes):
    """Wrap bytes in a stub exposing .read(), mimicking a boto3 StreamingBody."""
    import io

    return io.BytesIO(data)


@pytest.fixture
def run() -> Run:
    """Sample running Run on vllm — used to derive S3 keys."""
    return Run(
        id=uuid.uuid4(),
        status=RunStatus.running,
        model=_MODEL,
        model_size_b=8,
        engine=Engine.vllm,
        gpu_type_required="L40S",
        scenario_path="scenarios/ramp.yaml",
    )


@pytest.fixture
def result(run) -> Result:
    """Sample Result for the run — drives leaderboard upserts."""
    return Result(
        id=uuid.uuid4(),
        run_id=run.id,
        model=run.model,
        engine="vllm",
        gpu_type=GpuType.L40S,
        scenario="scenarios/ramp.yaml",
        total_requests=100,
        success_count=99,
        error_count=1,
        success_rate=0.99,
        ttft_mean_s=0.12,
        ttft_median_s=0.10,
        ttft_p95_s=0.30,
        tpot_mean_s=0.02,
        e2e_mean_s=1.5,
        e2e_p95_s=2.0,
        tokens_per_second_mean=42.0,
        total_tokens_per_second=420.0,
        requests_per_second=5.0,
        total_duration_s=20.0,
    )


@pytest.fixture
def mock_s3(mocker):
    """Patch the boto3 client factory and unwrap asyncio.to_thread.

    Returns the MagicMock that stands in for the boto3 S3 client, so each
    test can drive its return values / side_effects and inspect call args.
    """
    client = mocker.MagicMock()
    client.exceptions.ClientError = ClientError
    mocker.patch("src.storage._client", return_value=client)
    mocker.patch(
        "asyncio.to_thread",
        side_effect=lambda fn, *args, **kw: fn(*args, **kw),
    )
    return client


class TestUploadResults:
    """upload_results PUTs JSONL under runs/<id>/ and refreshes latest.jsonl."""

    async def test_should_return_per_run_key_under_model_engine_prefix(
        self, mock_s3, run
    ):
        """
        Should return the per-run S3 key under the (model, engine) prefix.

        Given: A Run for meta-llama/Llama-3.1-8B-Instruct on vllm
        When:  upload_results uploads the JSONL
        Then:  Returns results/<slug>/<engine>/runs/<run_id>/results.jsonl
        """
        # Given / When
        key = await upload_results(run, '{"tokens": 42}')

        # Then
        assert key == f"results/{_SLUG}/vllm/runs/{run.id}/results.jsonl"

    async def test_should_refresh_latest_jsonl_via_copy_object(self, mock_s3, run):
        """
        Should server-side copy the freshly-uploaded JSONL to latest.jsonl
        so dedup readers can fetch it without knowing the run UUID.

        Given: A successful per-run PUT
        When:  upload_results completes
        Then:  copy_object is called once pointing latest.jsonl at the new blob
        """
        # Given / When
        await upload_results(run, "{}")

        # Then
        mock_s3.copy_object.assert_called_once()
        kwargs = mock_s3.copy_object.call_args.kwargs
        assert kwargs["Key"] == f"results/{_SLUG}/vllm/latest.jsonl"
        assert kwargs["CopySource"]["Key"].endswith(f"runs/{run.id}/results.jsonl")


class TestUploadMeta:
    """upload_meta writes latest.meta.json — the dedup signal."""

    async def test_should_write_meta_payload_with_run_attributes(self, mock_s3, run):
        """
        Should PUT latest.meta.json containing the run identifiers
        consumers need to decide whether to skip a future bench.

        Given: A completed Run + git sha
        When:  upload_meta is called
        Then:  latest.meta.json is PUT with run_id, model, engine, git_sha
        """
        # Given / When
        key = await upload_meta(run, git_sha="abc123")

        # Then
        assert key == f"results/{_SLUG}/vllm/latest.meta.json"
        put_kwargs = mock_s3.put_object.call_args.kwargs
        assert put_kwargs["Key"] == key
        body = put_kwargs["Body"].decode()
        assert str(run.id) in body
        assert _MODEL in body
        assert '"engine":"vllm"' in body
        assert '"git_sha":"abc123"' in body


class TestHeadLatestMeta:
    """head_latest_meta is the S3-backed boolean used by bench_service dedup."""

    async def test_should_return_true_when_meta_exists(self, mock_s3):
        """
        Given: head_object succeeds (object present)
        When:  head_latest_meta is called
        Then:  Returns True
        """
        # Given
        mock_s3.head_object.return_value = {}

        # When
        exists = await head_latest_meta(_MODEL, Engine.vllm)

        # Then
        assert exists is True

    async def test_should_return_false_when_meta_missing(self, mock_s3):
        """
        Given: head_object raises a 404 ClientError
        When:  head_latest_meta is called
        Then:  Returns False (swallows the 404)
        """
        # Given
        mock_s3.head_object.side_effect = ClientError(
            {"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject"
        )

        # When
        exists = await head_latest_meta("foo/bar", Engine.llamacpp)

        # Then
        assert exists is False

    async def test_should_reraise_non_404_client_errors(self, mock_s3):
        """
        Given: head_object raises a non-404 ClientError (e.g. AccessDenied)
        When:  head_latest_meta is called
        Then:  The error propagates — dedup must not silently say "missing"
        """
        # Given
        mock_s3.head_object.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "nope"}}, "HeadObject"
        )

        # When / Then
        with pytest.raises(ClientError):
            await head_latest_meta(_MODEL, Engine.vllm)


class TestPresignedUrl:
    """presigned_url builds a temporary download URL for a run's JSONL."""

    async def test_should_sign_the_per_run_results_key(self, mock_s3, run):
        """
        Should generate the presigned URL against the per-run key, not the
        latest.jsonl alias (callers want a specific run, not 'the current one').

        Given: A boto3 client returning a fake signed URL
        When:  presigned_url is called for a run
        Then:  Returns that URL and signs the per-run results key
        """
        # Given
        fake_url = (
            "https://s3.fr-par.scw.cloud/bucket/results/.../results.jsonl?sig=abc"
        )
        mock_s3.generate_presigned_url.return_value = fake_url

        # When
        url = await presigned_url(run)

        # Then
        assert url == fake_url
        params = mock_s3.generate_presigned_url.call_args.kwargs["Params"]
        assert params["Key"] == f"results/{_SLUG}/vllm/runs/{run.id}/results.jsonl"


class TestPresignedLogsUrl:
    """presigned_logs_url signs the per-run runner.log key."""

    async def test_should_sign_the_per_run_logs_key(self, mock_s3, run):
        """
        Given: A boto3 client returning a fake signed URL
        When:  presigned_logs_url is called for a run
        Then:  Returns that URL and signs the per-run runner.log key
        """
        # Given
        mock_s3.generate_presigned_url.return_value = "https://signed/runner.log"

        # When
        url = await presigned_logs_url(run)

        # Then
        assert url == "https://signed/runner.log"
        params = mock_s3.generate_presigned_url.call_args.kwargs["Params"]
        assert params["Key"] == f"results/{_SLUG}/vllm/runs/{run.id}/runner.log"


class TestUploadLogs:
    """upload_logs PUTs the runner log under the per-run prefix."""

    async def test_should_put_log_and_return_per_run_key(self, mock_s3, run):
        """
        Given: Raw runner log bytes
        When:  upload_logs is called
        Then:  Returns the per-run runner.log key and PUTs the bytes
        """
        # Given / When
        key = await upload_logs(run, b"hello log")

        # Then
        assert key == f"results/{_SLUG}/vllm/runs/{run.id}/runner.log"
        put_kwargs = mock_s3.put_object.call_args.kwargs
        assert put_kwargs["Key"] == key
        assert put_kwargs["Body"] == b"hello log"


class TestFetchLogs:
    """fetch_logs downloads runner.log or returns None when absent."""

    async def test_should_return_bytes_when_present(self, mock_s3, run):
        """
        Given: get_object returns a log body
        When:  fetch_logs is called
        Then:  Returns the raw bytes
        """
        # Given
        mock_s3.get_object.return_value = {"Body": _body(b"log line")}

        # When
        out = await fetch_logs(run)

        # Then
        assert out == b"log line"

    async def test_should_return_none_when_missing(self, mock_s3, run):
        """
        Given: get_object raises NoSuchKey
        When:  fetch_logs is called
        Then:  Returns None (swallows the 404)
        """
        # Given
        mock_s3.get_object.side_effect = ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "nope"}}, "GetObject"
        )

        # When / Then
        assert await fetch_logs(run) is None

    async def test_should_reraise_non_404(self, mock_s3, run):
        """
        Given: get_object raises AccessDenied
        When:  fetch_logs is called
        Then:  The error propagates
        """
        # Given
        mock_s3.get_object.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "nope"}}, "GetObject"
        )

        # When / Then
        with pytest.raises(ClientError):
            await fetch_logs(run)


class TestFetchLatestResults:
    """fetch_latest_results downloads latest.jsonl or returns None."""

    async def test_should_return_bytes_when_present(self, mock_s3):
        """
        Given: get_object returns the latest JSONL
        When:  fetch_latest_results is called
        Then:  Returns the raw bytes from the latest.jsonl key
        """
        # Given
        mock_s3.get_object.return_value = {"Body": _body(b'{"x":1}')}

        # When
        out = await fetch_latest_results(_MODEL, Engine.vllm)

        # Then
        assert out == b'{"x":1}'
        assert mock_s3.get_object.call_args.kwargs["Key"] == (
            f"results/{_SLUG}/vllm/latest.jsonl"
        )

    async def test_should_return_none_when_missing(self, mock_s3):
        """
        Given: get_object raises a 404
        When:  fetch_latest_results is called
        Then:  Returns None
        """
        # Given
        mock_s3.get_object.side_effect = ClientError(
            {"Error": {"Code": "404", "Message": "nope"}}, "GetObject"
        )

        # When / Then
        assert await fetch_latest_results(_MODEL, Engine.vllm) is None


class TestListCompleted:
    """list_completed scans results/ for every latest.meta.json."""

    async def test_should_parse_only_latest_meta_objects(self, mock_s3, run):
        """
        Should ignore per-run artefacts and parse only latest.meta.json blobs.

        Given: A paginator yielding a mix of keys, one of them latest.meta.json
        When:  list_completed runs
        Then:  Only the meta object is fetched and parsed into CompletedRunMeta
        """
        # Given
        meta_key = f"results/{_SLUG}/vllm/latest.meta.json"
        meta_body = json.dumps(
            {
                "run_id": str(run.id),
                "model": _MODEL,
                "engine": "vllm",
                "scenario": "scenarios/ramp.yaml",
                "completed_at": "2026-05-26T00:00:00+00:00",
                "git_sha": "abc123",
            }
        ).encode()
        paginator = mock_s3.get_paginator.return_value
        paginator.paginate.return_value = [
            {
                "Contents": [
                    {"Key": f"results/{_SLUG}/vllm/runs/{run.id}/results.jsonl"},
                    {"Key": meta_key},
                ]
            }
        ]
        mock_s3.get_object.return_value = {"Body": _body(meta_body)}

        # When
        out = await list_completed()

        # Then
        assert len(out) == 1
        assert out[0].model == _MODEL
        assert out[0].engine == "vllm"
        assert mock_s3.get_object.call_args.kwargs["Key"] == meta_key

    async def test_should_return_empty_when_no_contents(self, mock_s3):
        """
        Given: A paginator page with no Contents
        When:  list_completed runs
        Then:  Returns an empty list
        """
        # Given
        mock_s3.get_paginator.return_value.paginate.return_value = [{}]

        # When / Then
        assert await list_completed() == []


class TestFetchLeaderboard:
    """fetch_leaderboard downloads leaderboard.json or returns None."""

    async def test_should_return_bytes_when_present(self, mock_s3):
        """
        Given: get_object returns the leaderboard payload
        When:  fetch_leaderboard is called
        Then:  Returns the raw bytes
        """
        # Given
        mock_s3.get_object.return_value = {"Body": _body(b"[]")}

        # When / Then
        assert await fetch_leaderboard() == b"[]"

    async def test_should_return_none_when_missing(self, mock_s3):
        """
        Given: get_object raises a 404
        When:  fetch_leaderboard is called
        Then:  Returns None
        """
        # Given
        mock_s3.get_object.side_effect = ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "nope"}}, "GetObject"
        )

        # When / Then
        assert await fetch_leaderboard() is None


class TestPublicCatalogUploads:
    """leaderboard/models/scenarios uploads are public-read at bucket root."""

    @pytest.mark.parametrize(
        "fn, expected_key",
        [
            (upload_leaderboard, "leaderboard.json"),
            (upload_models_catalog, "models.json"),
            (upload_scenarios_catalog, "scenarios.json"),
        ],
    )
    async def test_should_put_public_read_json_at_root(self, mock_s3, fn, expected_key):
        """
        Given: A JSON payload
        When:  the catalog uploader runs
        Then:  PUTs it public-read at the expected bucket-root key
        """
        # Given / When
        key = await fn("[]")

        # Then
        assert key == expected_key
        put_kwargs = mock_s3.put_object.call_args.kwargs
        assert put_kwargs["Key"] == expected_key
        assert put_kwargs["ACL"] == "public-read"
        assert put_kwargs["ContentType"] == "application/json"


class TestUpdateLeaderboardFor:
    """update_leaderboard_for upserts one (model, engine) row."""

    async def test_should_append_entry_to_empty_leaderboard(self, mock_s3, run, result):
        """
        Given: No existing leaderboard (get_object 404)
        When:  update_leaderboard_for runs
        Then:  A single entry is written for this (model, engine)
        """
        # Given
        mock_s3.get_object.side_effect = ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "nope"}}, "GetObject"
        )

        # When
        await update_leaderboard_for(run, result, per_concurrency=[{"c": 1}])

        # Then
        written = json.loads(mock_s3.put_object.call_args.kwargs["Body"].decode())
        assert len(written) == 1
        assert written[0]["model"] == _MODEL
        assert written[0]["engine"] == "vllm"
        assert written[0]["per_concurrency"] == [{"c": 1}]

    async def test_should_replace_stale_entry_for_same_model_engine(
        self, mock_s3, run, result
    ):
        """
        Should drop the prior (model, engine) row and keep unrelated ones.

        Given: A leaderboard holding a stale row for this pair plus another model
        When:  update_leaderboard_for runs
        Then:  The stale row is replaced; the unrelated row survives
        """
        # Given
        existing = [
            {"model": _MODEL, "engine": "vllm", "tokens_per_second_mean": 1.0},
            {"model": "other/model", "engine": "vllm"},
        ]
        mock_s3.get_object.return_value = {"Body": _body(json.dumps(existing).encode())}

        # When
        await update_leaderboard_for(run, result)

        # Then
        written = json.loads(mock_s3.put_object.call_args.kwargs["Body"].decode())
        models = sorted(e["model"] for e in written)
        assert models == [_MODEL, "other/model"]
        fresh = next(e for e in written if e["model"] == _MODEL)
        assert fresh["tokens_per_second_mean"] == 42.0
