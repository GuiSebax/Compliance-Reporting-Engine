"""MongoDB implementation of ``app.application.rejection_store.RejectionStore``.

One collection, ``ingestion_rejections``, one document per rejected row::

    {
      "batch_id": "…",              # joins back to PostgreSQL ``batches.id``
      "row_index": 17,
      "source_filename": "q1.csv",
      "source_format": "csv",
      "file_checksum_sha256": "…",
      "raw_payload": { … },         # the row exactly as received — any shape
      "reason": "…",
      "errors": [{"loc": "amount", "type": "decimal_parsing", "msg": "…"}],
      "rejected_at": ISODate(…)     # TTL-indexed: documents expire
    }

``raw_payload`` is the reason this lives in Mongo: its shape is decided by
the uploader, not by us, and varies row to row.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pymongo import ASCENDING
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

from app.application.rejection_store import (
    RejectionContext,
    RejectionDetail,
    RejectionStoreUnavailableError,
)
from app.schemas.batches import RejectedRowDetail, ValidationErrorDetail

COLLECTION_NAME = "ingestion_rejections"

# BSON's integer type is signed 64-bit; anything wider must be stringified.
_INT64_MAX = 2**63 - 1
_INT64_MIN = -(2**63)


def sanitize_for_bson(value: Any) -> Any:
    """Make an arbitrary parsed-upload value safe to store as BSON.

    Uploaded rows are untrusted and only *loosely* typed, so they contain
    things BSON cannot encode as-is:

    * ``Decimal`` — the JSON parser is run with ``parse_float=Decimal`` to
      keep monetary precision; stored as its exact string form, never as a
      float.
    * non-string keys — ``csv.DictReader`` uses ``None`` as the key for
      cells beyond the header width (with a *list* as value).
    * integers wider than 64 bits, ``bytes``, sets, arbitrary objects.
    * ``NUL`` characters in keys, which BSON forbids.
    """
    if value is None or isinstance(value, bool | str | float):
        return value
    if isinstance(value, int):
        return value if _INT64_MIN <= value <= _INT64_MAX else str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value
    if isinstance(value, dict):
        return {str(k).replace("\x00", "\\0"): sanitize_for_bson(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [sanitize_for_bson(v) for v in value]
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


class MongoRejectionStore:
    def __init__(self, collection: Collection, *, ttl_days: int) -> None:
        if ttl_days < 1:
            raise ValueError("ttl_days must be at least 1")
        self._collection = collection
        self._ttl_seconds = ttl_days * 24 * 60 * 60

    def ensure_indexes(self) -> None:
        """Idempotently create the indexes this store relies on.

        * ``(batch_id, row_index)`` — the only read path: "the rejections
          of batch X, in row order".
        * TTL on ``rejected_at`` — MongoDB itself deletes documents older
          than the retention window; no cleanup job to build or operate.
        """
        self._collection.create_index(
            [("batch_id", ASCENDING), ("row_index", ASCENDING)], name="ix_batch_row"
        )
        self._collection.create_index(
            [("rejected_at", ASCENDING)],
            name="ttl_rejected_at",
            expireAfterSeconds=self._ttl_seconds,
        )

    def record(self, context: RejectionContext, rejections: Sequence[RejectionDetail]) -> int:
        if not rejections:
            return 0
        now = datetime.now(UTC)
        documents = [
            {
                "batch_id": context.batch_id,
                "row_index": r.row_index,
                "source_filename": context.source_filename,
                "source_format": context.source_format,
                "file_checksum_sha256": context.file_checksum_sha256,
                "raw_payload": sanitize_for_bson(r.raw_payload),
                "reason": r.reason,
                "errors": [dict(e) for e in r.errors],
                "rejected_at": now,
            }
            for r in rejections
        ]
        try:
            # ordered=False: one bad document must not abort the rest.
            result = self._collection.insert_many(documents, ordered=False)
        except PyMongoError as exc:
            raise RejectionStoreUnavailableError(str(exc)) from exc
        return len(result.inserted_ids)

    def list_for_batch(
        self, batch_id: str, *, limit: int = 100, offset: int = 0
    ) -> list[RejectedRowDetail]:
        try:
            cursor = (
                self._collection.find({"batch_id": batch_id})
                .sort("row_index", ASCENDING)
                .skip(offset)
                .limit(limit)
            )
            documents = list(cursor)
        except PyMongoError as exc:
            raise RejectionStoreUnavailableError(str(exc)) from exc
        return [_to_detail(doc) for doc in documents]

    def count_for_batch(self, batch_id: str) -> int:
        try:
            return self._collection.count_documents({"batch_id": batch_id})
        except PyMongoError as exc:
            raise RejectionStoreUnavailableError(str(exc)) from exc


def _to_detail(doc: dict[str, Any]) -> RejectedRowDetail:
    return RejectedRowDetail(
        id=str(doc["_id"]),
        batch_id=doc["batch_id"],
        row_index=doc["row_index"],
        reason=doc["reason"],
        errors=[ValidationErrorDetail(**e) for e in doc.get("errors", [])],
        raw_payload=doc["raw_payload"],
        source_filename=doc["source_filename"],
        source_format=doc["source_format"],
        rejected_at=doc["rejected_at"],
    )
