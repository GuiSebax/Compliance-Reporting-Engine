"""Report generation use case: the glue between persistence and the pure
domain engine.

This is intentionally the *only* place in the codebase that both (a)
touches the database/filesystem/S3 and (b) calls into
``app.domain.services.report_builder``. Keeping that intersection to one
module is what makes the domain layer testable without any of this
infrastructure, and makes this module's own tests (integration-level,
against a real/sqlite DB) the single place that needs to verify the
wiring is correct.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date

from sqlalchemy.orm import Session

from app.application import export_service
from app.domain.exceptions import UnknownRuleSetVersionError
from app.domain.models.transaction import Transaction
from app.domain.rules.registry import DEFAULT_RULE_SET_VERSION, get_rule_set
from app.domain.services.report_builder import build_report
from app.infrastructure.db.models import AuditLogEntryRecord, ReportLineItemRecord, ReportRun
from app.infrastructure.db.repositories.report_repository import ReportRepository
from app.infrastructure.db.repositories.transaction_repository import TransactionRepository
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)


def _to_domain_transaction(record) -> Transaction:
    return Transaction(
        external_id=record.external_id,
        timestamp=record.timestamp,
        amount=record.amount,
        currency=record.currency,
        counterparty=record.counterparty,
        raw_category_hint=record.raw_category_hint,
        metadata=record.extra_metadata or {},
    )


def generate_report(
    *,
    db: Session,
    period_start: date,
    period_end: date,
    rule_set_version: str | None,
    triggered_by_user_id: str,
) -> ReportRun:
    version = rule_set_version or DEFAULT_RULE_SET_VERSION
    try:
        rule_set = get_rule_set(version)
    except ValueError as exc:
        raise UnknownRuleSetVersionError(str(exc)) from exc

    report_repo = ReportRepository(db)
    report_run = report_repo.create_pending(
        period_start=period_start,
        period_end=period_end,
        rule_set_version=rule_set.version,
        rule_set_definition_hash=rule_set.definition_hash,
        triggered_by_user_id=triggered_by_user_id,
    )
    # Committed immediately, before any of the actual processing: if
    # generation later fails, this RUNNING row (and the eventual
    # FAILED status + error message written to it in the except branch
    # below) must survive as its own audit record rather than
    # disappearing in a rollback.
    db.commit()

    logger.info(
        "report_generation_started",
        report_run_id=report_run.id,
        period_start=str(period_start),
        period_end=str(period_end),
        rule_set_version=rule_set.version,
    )

    try:
        tx_repo = TransactionRepository(db)
        records = tx_repo.list_for_period(period_start=period_start, period_end=period_end)
        transactions = [_to_domain_transaction(r) for r in records]

        result = build_report(
            transactions=transactions,
            rule_set=rule_set,
            period_start=period_start,
            period_end=period_end,
        )

        line_item_records = [
            ReportLineItemRecord(
                report_run_id=report_run.id,
                category=item.category,
                currency=item.currency,
                metric_name=item.metric_name,
                metric_value=item.metric_value,
                transaction_count=item.transaction_count,
                source_transaction_ids=list(item.source_transaction_ids),
            )
            for item in result.line_items
        ]
        report_repo.add_line_items(line_item_records)

        audit_records = [
            AuditLogEntryRecord(
                report_run_id=report_run.id,
                event_type=str(event.event_type),
                message=event.message,
                details=event.details,
                occurred_at=event.occurred_at,
            )
            for event in result.audit_trail
        ]
        report_repo.add_audit_entries(audit_records)

        # Exports are generated from the same in-memory ReportResult that
        # was just persisted, so file contents and DB rows can never
        # disagree with each other.
        json_path = export_service.write_json_export(result, report_run.id)
        csv_path = export_service.write_csv_export(result, report_run.id)
        pdf_path = export_service.write_pdf_export(result, report_run.id)
        s3_keys = export_service.upload_all_to_s3(
            report_run_id=report_run.id,
            json_path=json_path,
            csv_path=csv_path,
            pdf_path=pdf_path,
        )

        violations_payload = [asdict(v) for v in result.violations]
        for v in violations_payload:
            v["severity"] = str(v["severity"])

        report_repo.mark_completed(
            report_run,
            input_transaction_count=result.input_transaction_count,
            input_data_hash=result.input_data_hash,
            violations=violations_payload,
            export_json_path=json_path,
            export_csv_path=csv_path,
            export_pdf_path=pdf_path,
            **s3_keys,
        )

        db.commit()

        logger.info(
            "report_generation_completed",
            report_run_id=report_run.id,
            input_transaction_count=result.input_transaction_count,
            line_item_count=len(result.line_items),
            violation_count=len(result.violations),
        )
        return report_run

    except (
        Exception
    ) as exc:  # noqa: BLE001 - deliberately broad: any failure must mark the run failed
        db.rollback()
        report_repo = ReportRepository(db)
        failed_run = report_repo.get_by_id(report_run.id) or report_run
        report_repo.mark_failed(failed_run, error_message=str(exc))
        db.commit()
        logger.error("report_generation_failed", report_run_id=report_run.id, error=str(exc))
        raise
