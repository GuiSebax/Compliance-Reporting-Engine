from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.db.models import Batch, BatchStatus, TransactionRecord


class BatchRepository:
    def __init__(self, session: Session):
        self._session = session

    def create(
        self,
        *,
        uploaded_by_user_id: str,
        original_filename: str,
        content_type: str,
        checksum_sha256: str,
    ) -> Batch:
        batch = Batch(
            uploaded_by_user_id=uploaded_by_user_id,
            original_filename=original_filename,
            content_type=content_type,
            checksum_sha256=checksum_sha256,
            status=BatchStatus.PROCESSING,
        )
        self._session.add(batch)
        self._session.flush()
        return batch

    def add_transactions(self, records: list[TransactionRecord]) -> None:
        self._session.add_all(records)

    def finalize(
        self,
        batch: Batch,
        *,
        row_count: int,
        accepted_row_count: int,
        rejected_row_count: int,
        rejected_rows: list[dict],
    ) -> Batch:
        batch.row_count = row_count
        batch.accepted_row_count = accepted_row_count
        batch.rejected_row_count = rejected_row_count
        batch.rejected_rows = rejected_rows
        batch.status = BatchStatus.COMPLETED if accepted_row_count > 0 else BatchStatus.FAILED
        self._session.flush()
        return batch

    def get_by_id(self, batch_id: str) -> Batch | None:
        return self._session.get(Batch, batch_id)

    def list_recent(self, *, limit: int = 50, offset: int = 0) -> list[Batch]:
        stmt = select(Batch).order_by(Batch.created_at.desc()).limit(limit).offset(offset)
        return list(self._session.scalars(stmt))
