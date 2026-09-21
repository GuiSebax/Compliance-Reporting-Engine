"""AWS Lambda entrypoint: generate the compliance report for a period on a schedule.

Deployed as a container image (``backend/Dockerfile.lambda``) with the
handler ``app.lambda_handlers.scheduled_report.handler``, and triggered by
an EventBridge rule (``cron(0 3 1 * ? *)`` = 03:00 UTC on the 1st of each
month, which reports the month that just ended).

This module is an *inbound adapter*, the Lambda counterpart of a FastAPI
router: it parses and validates the event, manages the DB session, and
delegates to ``app.application.scheduled_report_service`` — which in turn
reuses ``report_service.generate_report``. There is no rule or reporting
logic here.

Accepted events
---------------
* The standard EventBridge scheduled event (``{"time": "2026-02-01T03:00:00Z",
  "detail-type": "Scheduled Event", ...}``) — reports the month before ``time``.
* An explicit override, for backfills and manual invocations::

      {"period_start": "2026-01-01", "period_end": "2026-01-31", "rule_set_version": "v1"}

* ``{}`` — treated as "now": reports the previous calendar month.

Errors are re-raised on purpose: a failed invocation must be *visible* to
Lambda (Errors metric, async retries, DLQ/on-failure destination) rather
than swallowed into a 200.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from app.application.scheduled_report_service import (
    previous_month_period,
    run_scheduled_report,
)
from app.infrastructure.db.models import ReportRun
from app.infrastructure.db.session import SessionLocal
from app.infrastructure.logging import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)


class ScheduledReportEvent(BaseModel):
    """The subset of the incoming event this function understands.

    ``extra="ignore"``: EventBridge wraps the payload in an envelope
    (``version``, ``id``, ``account``, ``resources`` …) we do not care about.
    """

    model_config = ConfigDict(extra="ignore")

    time: datetime | None = None
    period_start: date | None = None
    period_end: date | None = None
    rule_set_version: str | None = None

    @model_validator(mode="after")
    def _validate_period_override(self) -> ScheduledReportEvent:
        if (self.period_start is None) != (self.period_end is None):
            raise ValueError("period_start and period_end must be provided together")
        if self.period_start and self.period_end and self.period_end < self.period_start:
            raise ValueError("period_end must not be before period_start")
        return self

    def resolve_period(self, *, now: datetime | None = None) -> tuple[date, date]:
        if self.period_start and self.period_end:
            return self.period_start, self.period_end
        reference = self.time or now or datetime.now(UTC)
        reference_utc = reference if reference.tzinfo else reference.replace(tzinfo=UTC)
        return previous_month_period(reference_utc.astimezone(UTC).date())


def _summarize(report_run: ReportRun, *, reused_existing: bool) -> dict[str, Any]:
    return {
        "report_run_id": report_run.id,
        "status": str(report_run.status),
        "period_start": report_run.period_start.isoformat(),
        "period_end": report_run.period_end.isoformat(),
        "rule_set_version": report_run.rule_set_version,
        "input_transaction_count": report_run.input_transaction_count,
        "violation_count": len(report_run.violations or []),
        "reused_existing": reused_existing,
    }


def handler(event: dict[str, Any] | None, context: object | None = None) -> dict[str, Any]:
    """Lambda entrypoint. Returns a JSON-serializable run summary."""
    try:
        parsed = ScheduledReportEvent.model_validate(event or {})
    except ValidationError as exc:
        logger.error("scheduled_report_invalid_event", error=str(exc))
        raise

    period_start, period_end = parsed.resolve_period()
    logger.info(
        "scheduled_report_invoked",
        period_start=str(period_start),
        period_end=str(period_end),
        rule_set_version=parsed.rule_set_version,
        request_id=getattr(context, "aws_request_id", None),
    )

    db = SessionLocal()
    try:
        outcome = run_scheduled_report(
            db=db,
            period_start=period_start,
            period_end=period_end,
            rule_set_version=parsed.rule_set_version,
        )
        return _summarize(outcome.report_run, reused_existing=outcome.reused_existing)
    except Exception as exc:
        logger.error(
            "scheduled_report_failed",
            period_start=str(period_start),
            period_end=str(period_end),
            error=str(exc),
        )
        raise
    finally:
        db.close()
