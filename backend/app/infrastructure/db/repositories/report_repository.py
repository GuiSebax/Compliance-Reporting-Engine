from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.infrastructure.db.models import (
    AuditLogEntryRecord,
    ReportLineItemRecord,
    ReportRun,
    ReportRunStatus,
)


class ReportRepository:
    def __init__(self, session: Session):
        self._session = session

    def create_pending(
        self,
        *,
        period_start,
        period_end,
        rule_set_version: str,
        rule_set_definition_hash: str,
        triggered_by_user_id: str,
    ) -> ReportRun:
        report_run = ReportRun(
            period_start=period_start,
            period_end=period_end,
            rule_set_version=rule_set_version,
            rule_set_definition_hash=rule_set_definition_hash,
            status=ReportRunStatus.RUNNING,
            triggered_by_user_id=triggered_by_user_id,
            input_data_hash="",
        )
        self._session.add(report_run)
        self._session.flush()
        return report_run

    def add_line_items(self, records: list[ReportLineItemRecord]) -> None:
        self._session.add_all(records)

    def add_audit_entries(self, records: list[AuditLogEntryRecord]) -> None:
        self._session.add_all(records)

    def mark_completed(
        self,
        report_run: ReportRun,
        *,
        input_transaction_count: int,
        input_data_hash: str,
        violations: list[dict],
        export_json_path: str | None = None,
        export_csv_path: str | None = None,
        export_pdf_path: str | None = None,
        s3_json_key: str | None = None,
        s3_csv_key: str | None = None,
        s3_pdf_key: str | None = None,
    ) -> ReportRun:
        report_run.status = ReportRunStatus.COMPLETED
        report_run.input_transaction_count = input_transaction_count
        report_run.input_data_hash = input_data_hash
        report_run.violations = violations
        report_run.finished_at = datetime.utcnow()
        report_run.export_json_path = export_json_path
        report_run.export_csv_path = export_csv_path
        report_run.export_pdf_path = export_pdf_path
        report_run.s3_json_key = s3_json_key
        report_run.s3_csv_key = s3_csv_key
        report_run.s3_pdf_key = s3_pdf_key
        self._session.flush()
        return report_run

    def mark_failed(self, report_run: ReportRun, *, error_message: str) -> ReportRun:
        report_run.status = ReportRunStatus.FAILED
        report_run.error_message = error_message
        report_run.finished_at = datetime.utcnow()
        self._session.flush()
        return report_run

    def find_completed(
        self,
        *,
        period_start: date,
        period_end: date,
        rule_set_version: str,
        triggered_by_user_id: str,
    ) -> ReportRun | None:
        """Latest COMPLETED run for exactly this period/rule set/trigger, if any."""
        stmt = (
            select(ReportRun)
            .where(
                ReportRun.period_start == period_start,
                ReportRun.period_end == period_end,
                ReportRun.rule_set_version == rule_set_version,
                ReportRun.triggered_by_user_id == triggered_by_user_id,
                ReportRun.status == ReportRunStatus.COMPLETED,
            )
            .order_by(ReportRun.created_at.desc())
            .limit(1)
        )
        return self._session.scalar(stmt)

    def get_by_id(self, report_run_id: str) -> ReportRun | None:
        stmt = (
            select(ReportRun)
            .where(ReportRun.id == report_run_id)
            .options(
                selectinload(ReportRun.line_items),
                selectinload(ReportRun.audit_entries),
            )
        )
        return self._session.scalar(stmt)

    def list_recent(self, *, limit: int = 50, offset: int = 0) -> list[ReportRun]:
        stmt = select(ReportRun).order_by(ReportRun.created_at.desc()).limit(limit).offset(offset)
        return list(self._session.scalars(stmt))
