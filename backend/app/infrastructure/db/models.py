"""SQLAlchemy ORM models.

Deliberate modeling choices, worth defending in review:

- ``amount`` is ``Numeric(18, 2)`` everywhere, never ``Float`` — financial
  values must never go through binary floating point.
- JSON columns use the portable ``sqlalchemy.JSON`` type rather than
  Postgres' native ``JSONB``. This is a conscious trade-off: we give up a
  bit of native Postgres query power over JSON blobs in exchange for the
  integration test suite being able to run against SQLite with zero
  external services, which keeps CI fast and dependency-free. Postgres
  is still what runs in Docker/production.
- Rule *definitions* are versioned in code (``app.domain.rules.registry``),
  not in the database — a ``ReportRun`` only stores the version string and
  a content hash of the rule set that executed. This keeps "what rules
  exist" under normal code review/git history instead of needing a
  separate runtime-editable admin surface, while the hash still lets an
  auditor detect if the code registry ever silently changed underneath a
  version name.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.infrastructure.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class BatchStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ReportRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    uploaded_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[BatchStatus] = mapped_column(
        Enum(BatchStatus, native_enum=False, length=20), default=BatchStatus.PENDING
    )
    row_count: Mapped[int] = mapped_column(default=0)
    accepted_row_count: Mapped[int] = mapped_column(default=0)
    rejected_row_count: Mapped[int] = mapped_column(default=0)
    rejected_rows: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    transactions: Mapped[list[TransactionRecord]] = relationship(back_populates="batch")

    __table_args__ = (Index("ix_batches_created_at", "created_at"),)


class TransactionRecord(Base):
    """Persisted representation of ``app.domain.models.transaction.Transaction``."""

    __tablename__ = "transactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    counterparty: Mapped[str] = mapped_column(String(255), nullable=False)
    raw_category_hint: Mapped[str | None] = mapped_column(String(50), nullable=True)
    extra_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    batch: Mapped[Batch] = relationship(back_populates="transactions")

    __table_args__ = (
        Index("ix_transactions_batch_id", "batch_id"),
        Index("ix_transactions_timestamp", "timestamp"),
    )


class ReportRun(Base):
    __tablename__ = "report_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    period_start: Mapped[date] = mapped_column(nullable=False)
    period_end: Mapped[date] = mapped_column(nullable=False)
    rule_set_version: Mapped[str] = mapped_column(String(20), nullable=False)
    rule_set_definition_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[ReportRunStatus] = mapped_column(
        Enum(ReportRunStatus, native_enum=False, length=20), default=ReportRunStatus.PENDING
    )
    input_transaction_count: Mapped[int] = mapped_column(default=0)
    input_data_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    violations: Mapped[list[dict]] = mapped_column(JSON, default=list)
    triggered_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    export_json_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    export_csv_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    export_pdf_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    s3_json_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    s3_csv_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    s3_pdf_key: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    line_items: Mapped[list[ReportLineItemRecord]] = relationship(
        back_populates="report_run", cascade="all, delete-orphan"
    )
    audit_entries: Mapped[list[AuditLogEntryRecord]] = relationship(
        back_populates="report_run", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_report_runs_period", "period_start", "period_end"),)


class ReportLineItemRecord(Base):
    __tablename__ = "report_line_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    report_run_id: Mapped[str] = mapped_column(ForeignKey("report_runs.id"), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    metric_name: Mapped[str] = mapped_column(String(50), nullable=False)
    metric_value: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    transaction_count: Mapped[int] = mapped_column(default=0)
    source_transaction_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)

    report_run: Mapped[ReportRun] = relationship(back_populates="line_items")

    __table_args__ = (Index("ix_report_line_items_report_run_id", "report_run_id"),)


class AuditLogEntryRecord(Base):
    __tablename__ = "audit_log_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    report_run_id: Mapped[str] = mapped_column(ForeignKey("report_runs.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    report_run: Mapped[ReportRun] = relationship(back_populates="audit_entries")

    __table_args__ = (Index("ix_audit_log_entries_report_run_id", "report_run_id"),)
