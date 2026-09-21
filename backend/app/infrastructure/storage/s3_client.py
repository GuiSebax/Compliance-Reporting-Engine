"""S3 (or S3-compatible) object storage client for report exports.

Pointing ``s3_endpoint_url`` at a LocalStack container makes this talk to
a fully local, disposable "AWS" for demos and CI — see
``docker-compose.yml`` and the README's "AWS / S3 export" section for how
to flip the same code path to a real AWS account (unset the endpoint
override, provide real credentials/region/bucket).

Upload failures are caught and logged rather than raised: a report is
still successfully generated and locally persisted even if the S3 upload
step fails (network blip, bucket not yet provisioned, LocalStack not
running) — the export just stays un-mirrored to S3 until retried, instead
of the whole report run being marked failed over what is, from the
report's own correctness standpoint, a non-essential side effect.
"""

from __future__ import annotations

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import get_settings
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)


def _client():
    settings = get_settings()
    return boto3.client(
        "s3",
        region_name=settings.s3_region,
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )


def ensure_bucket_exists() -> None:
    """Idempotently create the configured bucket (used for local/demo setup
    against LocalStack; a real AWS deployment would provision the bucket
    via infrastructure-as-code instead of at application startup)."""
    settings = get_settings()
    if settings.is_test:
        return
    client = _client()
    try:
        client.head_bucket(Bucket=settings.s3_bucket_name)
    except (ClientError, BotoCoreError):
        try:
            client.create_bucket(Bucket=settings.s3_bucket_name)
        except (ClientError, BotoCoreError) as exc:
            logger.warning("s3_bucket_setup_failed", bucket=settings.s3_bucket_name, error=str(exc))


def upload_file(*, local_path: str, key: str) -> str | None:
    """Upload a local file to S3, returning the object key on success or
    ``None`` if the upload could not be completed.

    A no-op in the test environment: outbound calls to a real or
    LocalStack S3 endpoint are deliberately not exercised by the unit/
    integration test suite (keeps CI fast, network-independent, and
    deterministic) — S3 upload behavior itself is exercised manually
    against LocalStack per the README, not asserted on in pytest.
    """
    settings = get_settings()
    if settings.is_test:
        logger.debug("s3_upload_skipped_in_test_environment", key=key)
        return None
    client = _client()
    try:
        client.upload_file(local_path, settings.s3_bucket_name, key)
        logger.info("s3_upload_succeeded", bucket=settings.s3_bucket_name, key=key)
        return key
    except (ClientError, BotoCoreError, OSError) as exc:
        logger.warning("s3_upload_failed", bucket=settings.s3_bucket_name, key=key, error=str(exc))
        return None
