"""Scheduled (unattended) report generation use case.

This is deliberately a *thin* layer over ``report_service.generate_report``:
the rule engine, aggregation, persistence, audit trail and exports are all
reused untouched. What it adds is only what an unattended run needs that an
authenticated API call does not:

* a **period policy** — the previous calendar month;
* an **identity** — there is no logged-in user, so runs are attributed to a
  dedicated, non-loginable service account;
* **idempotency** — EventBridge invokes Lambda asynchronously and retries
  failed invocations, so the same period must not be reported twice.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.application.report_service import generate_report
from app.domain.exceptions import UnknownRuleSetVersionError
from app.domain.rules.registry import DEFAULT_RULE_SET_VERSION, get_rule_set
from app.infrastructure.db.models import ReportRun, User
from app.infrastructure.db.repositories.report_repository import ReportRepository
from app.infrastructure.db.repositories.user_repository import UserRepository
from app.infrastructure.logging import get_logger
from app.infrastructure.security.passwords import hash_password

logger = get_logger(__name__)

SERVICE_ACCOUNT_EMAIL = "system@compliance.local"


@dataclass(frozen=True, slots=True)
class ScheduledReportOutcome:
    report_run: ReportRun
    # True when a completed run for this period already existed and was
    # returned instead of generating a duplicate (retry / double delivery).
    reused_existing: bool


def previous_month_period(reference: date) -> tuple[date, date]:
    """First and last day of the calendar month before ``reference``'s month."""
    last_day_prev_month = reference.replace(day=1) - timedelta(days=1)
    return last_day_prev_month.replace(day=1), last_day_prev_month


def get_or_create_service_account(db: Session) -> User:
    """The identity scheduled runs are attributed to.

    The account is inactive (so ``get_current_user`` rejects any token for
    it) and its password is a random value that is never stored or shown,
    so it cannot be used to log in. Created lazily so no migration or
    seeding step is needed.
    """
    repo = UserRepository(db)
    user = repo.get_by_email(SERVICE_ACCOUNT_EMAIL)
    if user is not None:
        return user
    try:
        with db.begin_nested():
            user = repo.create(
                email=SERVICE_ACCOUNT_EMAIL,
                hashed_password=hash_password(secrets.token_urlsafe(32)),
                is_active=False,
            )
    except IntegrityError:
        # A concurrent invocation created it first — use theirs.
        user = repo.get_by_email(SERVICE_ACCOUNT_EMAIL)
        if user is None:
            raise
    db.commit()
    return user


def run_scheduled_report(
    *,
    db: Session,
    period_start: date,
    period_end: date,
    rule_set_version: str | None = None,
) -> ScheduledReportOutcome:
    version = rule_set_version or DEFAULT_RULE_SET_VERSION
    try:
        resolved_version = get_rule_set(version).version
    except ValueError as exc:
        raise UnknownRuleSetVersionError(str(exc)) from exc

    service_user = get_or_create_service_account(db)

    existing = ReportRepository(db).find_completed(
        period_start=period_start,
        period_end=period_end,
        rule_set_version=resolved_version,
        triggered_by_user_id=service_user.id,
    )
    if existing is not None:
        logger.info(
            "scheduled_report_reused_existing",
            report_run_id=existing.id,
            period_start=str(period_start),
            period_end=str(period_end),
        )
        return ScheduledReportOutcome(report_run=existing, reused_existing=True)

    report_run = generate_report(
        db=db,
        period_start=period_start,
        period_end=period_end,
        rule_set_version=resolved_version,
        triggered_by_user_id=service_user.id,
    )
    return ScheduledReportOutcome(report_run=report_run, reused_existing=False)
