import asyncio
import uuid

import boto3
from botocore.config import Config

from src.config import settings

_SCW_ENDPOINT = f"https://s3.{settings.scw_region}.scw.cloud"


def _client():
    return boto3.client(
        "s3",
        endpoint_url=_SCW_ENDPOINT,
        region_name=settings.scw_region,
        aws_access_key_id=settings.scw_access_key,
        aws_secret_access_key=settings.scw_secret_key,
        config=Config(signature_version="s3v4"),
    )


def _results_key(run_id: uuid.UUID) -> str:
    return f"runs/{run_id}/results.jsonl"


def _logs_key(run_id: uuid.UUID) -> str:
    return f"runs/{run_id}/runner.log"


async def upload_results(run_id: uuid.UUID, jsonl: str) -> str:
    """Upload JSONL to Scaleway Object Storage, return the object key."""
    key = _results_key(run_id)
    client = _client()
    await asyncio.to_thread(
        client.put_object,
        Bucket=settings.scw_bucket,
        Key=key,
        Body=jsonl.encode(),
        ContentType="application/x-ndjson",
    )
    return key


async def fetch_logs(run_id: uuid.UUID) -> bytes | None:
    """Download runner log from S3. Returns None if the object doesn't exist."""
    client = _client()

    def _get():
        try:
            obj = client.get_object(Bucket=settings.scw_bucket, Key=_logs_key(run_id))
            return obj["Body"].read()
        except client.exceptions.NoSuchKey:
            return None

    return await asyncio.to_thread(_get)


async def upload_logs(run_id: uuid.UUID, content: bytes) -> str:
    """Upload runner log file, return the object key."""
    key = _logs_key(run_id)
    client = _client()
    await asyncio.to_thread(
        client.put_object,
        Bucket=settings.scw_bucket,
        Key=key,
        Body=content,
        ContentType="text/plain; charset=utf-8",
    )
    return key


async def presigned_url(run_id: uuid.UUID, expires: int = 3600) -> str:
    """Generate a presigned GET URL for the JSONL blob."""
    client = _client()
    return await asyncio.to_thread(
        client.generate_presigned_url,
        "get_object",
        Params={"Bucket": settings.scw_bucket, "Key": _results_key(run_id)},
        ExpiresIn=expires,
    )


async def presigned_logs_url(run_id: uuid.UUID, expires: int = 3600) -> str:
    client = _client()
    return await asyncio.to_thread(
        client.generate_presigned_url,
        "get_object",
        Params={"Bucket": settings.scw_bucket, "Key": _logs_key(run_id)},
        ExpiresIn=expires,
    )
