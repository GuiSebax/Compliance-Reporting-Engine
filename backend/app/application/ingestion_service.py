"""Batch ingestion use case: turn an uploaded CSV/JSON file into persisted,
validated transaction rows.

Validation happens in two independent layers, deliberately kept separate:

1. **Syntactic** — ``TransactionRowSchema`` (Pydantic) checks each row has
   the right shape and types. A row that fails this never reaches the
   database; it is recorded in ``rejected_rows`` with a reason and the
   batch proceeds with whatever rows *did* pass.
2. **Semantic/business** — the rule engine, applied later at report
   generation time (not here), classifies and flags rows that are
   syntactically valid but business-invalid (e.g. amount over a
   threshold with no counterparty). Ingestion does not run business
   rules — a bad-but-well-formed row is still stored, because
   compliance reporting needs to be able to say "this transaction
   existed and violated rule X", not silently drop it.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from datetime import UTC
from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.infrastructure.db.models import Batch, TransactionRecord
from app.infrastructure.db.repositories.batch_repository import BatchRepository
from app.infrastructure.logging import get_logger
from app.schemas.batches import RejectedRow, TransactionRowSchema

logger = get_logger(__name__)


class UnsupportedFileTypeError(Exception):
    pass


class BatchTooLargeError(Exception):
    pass


class EmptyUploadError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class IngestionResult:
    batch: Batch
    accepted_row_count: int
    rejected_row_count: int
    rejected_rows: list[RejectedRow]


_ALLOWED_EXTENSIONS = (".csv", ".json")


def _sniff_rows(filename: str, raw_bytes: bytes) -> list[dict]:
    """Parse raw upload bytes into a list of loosely-typed row dicts."""
    lower_name = filename.lower()
    if lower_name.endswith(".csv"):
        text = raw_bytes.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        return [dict(row) for row in reader]
    if lower_name.endswith(".json"):
        # parse_float=Decimal preserves exact decimal precision for JSON
        # numeric literals (e.g. 1999.99) instead of the default float,
        # so a monetary amount never silently picks up binary-float error.
        text = raw_bytes.decode("utf-8-sig")
        payload = json.loads(text, parse_float=Decimal)
        if isinstance(payload, dict) and "transactions" in payload:
            payload = payload["transactions"]
        if not isinstance(payload, list):
            raise ValueError(
                "JSON payload must be a list of transactions (or a "
                "{'transactions': [...]} object)."
            )
        return payload
    raise UnsupportedFileTypeError(
        f"Unsupported file type for '{filename}'. Allowed: {', '.join(_ALLOWED_EXTENSIONS)}"
    )


def ingest_batch(
    *,
    db: Session,
    uploaded_by_user_id: str,
    filename: str,
    content_type: str,
    raw_bytes: bytes,
) -> IngestionResult:
    settings = get_settings()

    if not raw_bytes:
        raise EmptyUploadError("Uploaded file is empty.")

    if len(raw_bytes) > settings.max_upload_size_bytes:
        raise BatchTooLargeError(
            f"Upload of {len(raw_bytes)} bytes exceeds the "
            f"{settings.max_upload_size_bytes}-byte limit."
        )

    # Sanitize: only the basename is ever persisted/used — never trust a
    # client-supplied path (path traversal via '../' etc.).
    safe_filename = filename.replace("\\", "/").rsplit("/", maxsplit=1)[-1] or "upload"

    checksum = hashlib.sha256(raw_bytes).hexdigest()

    raw_rows = _sniff_rows(safe_filename, raw_bytes)

    if len(raw_rows) > settings.max_transactions_per_batch:
        raise BatchTooLargeError(
            f"Batch has {len(raw_rows)} rows, exceeding the "
            f"{settings.max_transactions_per_batch}-row limit per batch."
        )

    batch_repo = BatchRepository(db)
    batch = batch_repo.create(
        uploaded_by_user_id=uploaded_by_user_id,
        original_filename=safe_filename,
        content_type=content_type,
        checksum_sha256=checksum,
    )

    accepted_records: list[TransactionRecord] = []
    rejected_rows: list[RejectedRow] = []

    for index, raw_row in enumerate(raw_rows):
        try:
            if not isinstance(raw_row, dict):
                raise ValueError("row is not a JSON object / CSV record")
            row = TransactionRowSchema.model_validate(raw_row)
        except (ValidationError, ValueError) as exc:
            rejected_rows.append(RejectedRow(row_index=index, reason=str(exc)))
            continue

        timestamp = row.timestamp if row.timestamp.tzinfo else row.timestamp.replace(tzinfo=UTC)
        accepted_records.append(
            TransactionRecord(
                batch_id=batch.id,
                external_id=row.external_id,
                timestamp=timestamp,
                amount=row.amount,
                currency=row.currency,
                counterparty=row.counterparty,
                raw_category_hint=row.raw_category_hint,
                extra_metadata=row.metadata or None,
            )
        )

    batch_repo.add_transactions(accepted_records)
    batch = batch_repo.finalize(
        batch,
        row_count=len(raw_rows),
        accepted_row_count=len(accepted_records),
        rejected_row_count=len(rejected_rows),
        rejected_rows=[r.model_dump() for r in rejected_rows],
    )

    logger.info(
        "batch_ingested",
        batch_id=batch.id,
        filename=safe_filename,
        row_count=len(raw_rows),
        accepted=len(accepted_records),
        rejected=len(rejected_rows),
        checksum=checksum,
    )

    return IngestionResult(
        batch=batch,
        accepted_row_count=len(accepted_records),
        rejected_row_count=len(rejected_rows),
        rejected_rows=rejected_rows,
    )
