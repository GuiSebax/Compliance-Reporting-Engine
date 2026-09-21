from __future__ import annotations

from datetime import UTC, date, datetime, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.db.models import TransactionRecord


class TransactionRepository:
    def __init__(self, session: Session):
        self._session = session

    def list_for_period(self, *, period_start: date, period_end: date) -> list[TransactionRecord]:
        # All transaction timestamps are normalized to UTC at ingestion time
        # (see app.application.ingestion_service), so period boundaries are
        # compared in UTC too — avoids ambiguity from naive/local datetimes.
        start_dt = datetime.combine(period_start, time.min, tzinfo=UTC)
        end_dt = datetime.combine(period_end, time.max, tzinfo=UTC)
        stmt = (
            select(TransactionRecord)
            .where(TransactionRecord.timestamp >= start_dt)
            .where(TransactionRecord.timestamp <= end_dt)
            .order_by(TransactionRecord.timestamp)
        )
        return list(self._session.scalars(stmt))
