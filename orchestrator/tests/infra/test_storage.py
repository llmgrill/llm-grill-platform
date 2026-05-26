"""
Tests for src.storage — model/engine-keyed S3 layout.

Covers the helpers that drive cross-cycle deduplication:
upload_results (+ latest.jsonl copy), upload_meta, head_latest_meta,
and presigned_url. All boto3 calls are patched; no Scaleway credentials needed.
"""

import uuid

import pytest
from botocore.exceptions import ClientError

from src.models import Engine, Run, RunStatus
from src.storage import (
    head_latest_meta,
    presigned_url,
    upload_meta,
    upload_results,
)

_MODEL = "meta-llama/Llama-3.1-8B-Instruct"
_SLUG = "meta-llama__Llama-3.1-8B-Instruct"


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
