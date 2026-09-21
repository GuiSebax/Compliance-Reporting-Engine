"""Forensic trail of rejected ingestion rows (the schema-flexible side of
the system's polyglot persistence).

Why this is *not* redundant with ``batches.rejected_rows`` in PostgreSQL:
that column keeps the relational summary the API returns (``row_index`` +
``reason``) and is part of the permanent compliance record. This store
keeps what the relational model has no good home for — the **original raw
payload** of each rejected row (whose shape differs per source: a CSV row
with unexpected extra columns, a JSON object with arbitrary nesting) plus
the structured validation errors — under a **retention policy**, because
raw rejected payloads are untrusted, possibly sensitive, and only useful
for a limited forensic window.

The concrete implementation lives in ``app.infrastructure.mongo``; this
module defines the contract so ingestion and the API depend on an
abstraction rather than on MongoDB.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from app.infrastructure.logging import get_logger
from app.schemas.batches import RejectedRowDetail

logger = get_logger(__name__)


class RejectionStoreUnavailableError(Exception):
    """The store is not configured or could not be reached."""


@dataclass(frozen=True, slots=True)
class RejectionDetail:
    """One rejected row, as seen at the moment of rejection."""

    row_index: int
    reason: str
    raw_payload: Any
    errors: tuple[dict[str, str], ...]


@dataclass(frozen=True, slots=True)
class RejectionContext:
    """Where the rejected rows came from."""

    batch_id: str
    source_filename: str
    source_format: str
    file_checksum_sha256: str


class RejectionStore(Protocol):
    def record(self, context: RejectionContext, rejections: Sequence[RejectionDetail]) -> int:
        """Persist rejections; returns how many were stored."""
        ...

    def list_for_batch(
        self, batch_id: str, *, limit: int = 100, offset: int = 0
    ) -> list[RejectedRowDetail]: ...

    def count_for_batch(self, batch_id: str) -> int: ...


class NullRejectionStore:
    """Used when MongoDB is not configured: recording is a no-op, reading
    reports the feature as unavailable (rather than pretending there are
    simply no rejections)."""

    def record(self, context: RejectionContext, rejections: Sequence[RejectionDetail]) -> int:
        return 0

    def list_for_batch(
        self, batch_id: str, *, limit: int = 100, offset: int = 0
    ) -> list[RejectedRowDetail]:
        raise RejectionStoreUnavailableError("Rejection trail store is not configured.")

    def count_for_batch(self, batch_id: str) -> int:
        raise RejectionStoreUnavailableError("Rejection trail store is not configured.")


def record_rejections_best_effort(
    store: RejectionStore,
    context: RejectionContext,
    rejections: Sequence[RejectionDetail],
) -> int:
    """Store rejections, swallowing (and logging) any failure.

    The forensic trail is a non-essential side effect of ingestion, exactly
    like the S3 mirror of report exports: losing it must never turn a
    successful ingestion into a failed one. Callers invoke this *after*
    the relational commit, so the trail can never reference a batch that
    does not exist.
    """
    if not rejections:
        return 0
    try:
        stored = store.record(context, rejections)
    except Exception as exc:  # noqa: BLE001 - deliberately broad: best-effort by design
        logger.warning(
            "rejection_trail_write_failed",
            batch_id=context.batch_id,
            rejected_rows=len(rejections),
            error=str(exc),
        )
        return 0
    logger.info("rejection_trail_written", batch_id=context.batch_id, stored=stored)
    return stored
