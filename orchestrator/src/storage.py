from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from src.config import settings
from src.models import Engine, Result, Run
from src.schemas import CompletedRunMeta

_SCW_ENDPOINT = f"https://s3.{settings.scw_region}.scw.cloud"

_LEADERBOARD_KEY = "leaderboard.json"

# Error codes S3 (AWS or Scaleway) returns for a missing object. head_object
# yields "404"/"NotFound" (no modeled exception), get_object yields "NoSuchKey".
_NOT_FOUND_CODES = {"404", "NoSuchKey", "NotFound"}


def _is_not_found(exc: ClientError) -> bool:
    return exc.response["Error"]["Code"] in _NOT_FOUND_CODES


def _client():
    return boto3.client(
        "s3",
        endpoint_url=_SCW_ENDPOINT,
        region_name=settings.scw_region,
        aws_access_key_id=settings.scw_access_key,
        aws_secret_access_key=settings.scw_secret_key,
        config=Config(signature_version="s3v4"),
    )


def _slug(model: str) -> str:
    return model.replace("/", "__")


def _engine_str(engine: Engine | str) -> str:
    return engine.value if isinstance(engine, Engine) else engine


def _run_results_key(model: str, engine: Engine | str, run_id: uuid.UUID) -> str:
    return f"results/{_slug(model)}/{_engine_str(engine)}/runs/{run_id}/results.jsonl"


def _run_logs_key(model: str, engine: Engine | str, run_id: uuid.UUID) -> str:
    return f"results/{_slug(model)}/{_engine_str(engine)}/runs/{run_id}/runner.log"


def _latest_results_key(model: str, engine: Engine | str) -> str:
    return f"results/{_slug(model)}/{_engine_str(engine)}/latest.jsonl"


def _latest_meta_key(model: str, engine: Engine | str) -> str:
    return f"results/{_slug(model)}/{_engine_str(engine)}/latest.meta.json"


async def upload_results(run: Run, jsonl: str) -> str:
    """Upload JSONL for a run and refresh the per-(model, engine) latest pointer.

    Returns the per-run S3 key.
    """
    run_key = _run_results_key(run.model, run.engine, run.id)
    latest_key = _latest_results_key(run.model, run.engine)
    client = _client()

    await asyncio.to_thread(
        client.put_object,
        Bucket=settings.scw_bucket,
        Key=run_key,
        Body=jsonl.encode(),
        ContentType="application/x-ndjson",
    )
    await asyncio.to_thread(
        client.copy_object,
        Bucket=settings.scw_bucket,
        Key=latest_key,
        CopySource={"Bucket": settings.scw_bucket, "Key": run_key},
        ContentType="application/x-ndjson",
        MetadataDirective="REPLACE",
    )
    return run_key


async def upload_meta(run: Run, git_sha: str | None = None) -> str:
    """Write latest.meta.json for (model, engine) — the dedup signal."""
    key = _latest_meta_key(run.model, run.engine)
    meta = CompletedRunMeta(
        run_id=run.id,
        model=run.model,
        engine=_engine_str(run.engine),
        scenario=run.scenario_path,
        completed_at=run.ended_at or datetime.now(timezone.utc),
        git_sha=git_sha,
    )
    client = _client()
    await asyncio.to_thread(
        client.put_object,
        Bucket=settings.scw_bucket,
        Key=key,
        Body=meta.model_dump_json().encode(),
        ContentType="application/json",
    )
    return key


async def head_latest_meta(model: str, engine: Engine | str) -> bool:
    """Return True iff a `latest.meta.json` exists for this (model, engine)."""
    client = _client()
    key = _latest_meta_key(model, engine)

    def _head() -> bool:
        try:
            client.head_object(Bucket=settings.scw_bucket, Key=key)
            return True
        except ClientError as exc:
            if _is_not_found(exc):
                return False
            raise

    return await asyncio.to_thread(_head)


async def list_completed() -> list[CompletedRunMeta]:
    """List every (model, engine) that has a `latest.meta.json` on S3."""
    client = _client()

    def _list() -> list[CompletedRunMeta]:
        paginator = client.get_paginator("list_objects_v2")
        out: list[CompletedRunMeta] = []
        for page in paginator.paginate(Bucket=settings.scw_bucket, Prefix="results/"):
            for obj in page.get("Contents", []) or []:
                key = obj["Key"]
                if not key.endswith("/latest.meta.json"):
                    continue
                blob = client.get_object(Bucket=settings.scw_bucket, Key=key)
                out.append(CompletedRunMeta.model_validate_json(blob["Body"].read()))
        return out

    return await asyncio.to_thread(_list)


async def fetch_latest_results(model: str, engine: Engine | str) -> bytes | None:
    """Download the JSONL for the latest completed run of (model, engine)."""
    client = _client()
    key = _latest_results_key(model, engine)

    def _get() -> bytes | None:
        try:
            obj = client.get_object(Bucket=settings.scw_bucket, Key=key)
            return obj["Body"].read()
        except ClientError as exc:
            if _is_not_found(exc):
                return None
            raise

    return await asyncio.to_thread(_get)


async def fetch_logs(run: Run) -> bytes | None:
    """Download runner log for a run. Returns None if the object doesn't exist."""
    client = _client()
    key = _run_logs_key(run.model, run.engine, run.id)

    def _get():
        try:
            obj = client.get_object(Bucket=settings.scw_bucket, Key=key)
            return obj["Body"].read()
        except ClientError as exc:
            if _is_not_found(exc):
                return None
            raise

    return await asyncio.to_thread(_get)


async def upload_logs(run: Run, content: bytes) -> str:
    """Upload runner log file, return the object key."""
    key = _run_logs_key(run.model, run.engine, run.id)
    client = _client()
    await asyncio.to_thread(
        client.put_object,
        Bucket=settings.scw_bucket,
        Key=key,
        Body=content,
        ContentType="text/plain; charset=utf-8",
    )
    return key


async def update_leaderboard_for(run: Run, result: Result) -> None:
    """Upsert one (model, engine) entry in leaderboard.json on S3.

    Reads the current leaderboard, drops any stale entry for this
    (model, engine), appends the fresh one, writes back. Cheaper than
    recomputing every entry from `latest.jsonl` and idempotent across retries.

    No concurrency control: this is a plain read-modify-write. Two completions
    landing within the same window could drop one entry. Accepted given run
    completions trickle in minutes apart; revisit with conditional writes
    (ETag/If-Match) if completions ever become bursty.
    """
    current = await fetch_leaderboard()
    entries: list[dict] = json.loads(current) if current else []
    engine_str = _engine_str(run.engine)
    entries = [
        e
        for e in entries
        if not (e.get("model") == run.model and e.get("engine") == engine_str)
    ]
    entries.append(
        {
            "model": run.model,
            "engine": engine_str,
            "gpu_type": result.gpu_type.value,
            "tokens_per_second_mean": result.tokens_per_second_mean,
            "total_tokens_per_second": result.total_tokens_per_second,
            "requests_per_second": result.requests_per_second,
            "e2e_p95_s": result.e2e_p95_s,
            "ttft_p95_s": result.ttft_p95_s,
            "success_rate": result.success_rate,
            "run_id": str(run.id),
            "measured_at": (run.ended_at or datetime.now(timezone.utc)).isoformat(),
        }
    )
    await upload_leaderboard(json.dumps(entries))


async def upload_leaderboard(payload: str) -> str:
    """Write the consolidated leaderboard.json at the bucket root.

    Marked public-read so the static frontend can fetch it directly from S3
    without going through the orchestrator (see docs/frontend-plan.md).
    """
    client = _client()
    await asyncio.to_thread(
        client.put_object,
        Bucket=settings.scw_bucket,
        Key=_LEADERBOARD_KEY,
        Body=payload.encode(),
        ContentType="application/json",
        ACL="public-read",
    )
    return _LEADERBOARD_KEY


async def fetch_leaderboard() -> bytes | None:
    """Download leaderboard.json from S3."""
    client = _client()

    def _get() -> bytes | None:
        try:
            obj = client.get_object(Bucket=settings.scw_bucket, Key=_LEADERBOARD_KEY)
            return obj["Body"].read()
        except ClientError as exc:
            if _is_not_found(exc):
                return None
            raise

    return await asyncio.to_thread(_get)


async def presigned_url(run: Run, expires: int = 3600) -> str:
    """Generate a presigned GET URL for the JSONL of a given run."""
    client = _client()
    return await asyncio.to_thread(
        client.generate_presigned_url,
        "get_object",
        Params={
            "Bucket": settings.scw_bucket,
            "Key": _run_results_key(run.model, run.engine, run.id),
        },
        ExpiresIn=expires,
    )


async def presigned_logs_url(run: Run, expires: int = 3600) -> str:
    client = _client()
    return await asyncio.to_thread(
        client.generate_presigned_url,
        "get_object",
        Params={
            "Bucket": settings.scw_bucket,
            "Key": _run_logs_key(run.model, run.engine, run.id),
        },
        ExpiresIn=expires,
    )
