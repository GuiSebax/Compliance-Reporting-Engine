"""Integration tests for the scheduled-report Lambda handler.

The handler is invoked exactly as Lambda would (``handler(event, context)``)
against an isolated in-memory SQLite database, exercising the *real*
``generate_report`` pipeline — nothing about report generation is mocked
except where a test needs to force a failure.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.application import report_service, scheduled_report_service
from app.application.ingestion_service import ingest_batch
from app.application.scheduled_report_service import SERVICE_ACCOUNT_EMAIL
from app.domain.exceptions import UnknownRuleSetVersionError
from app.infrastructure.db.models import ReportRun, ReportRunStatus, User
from app.lambda_handlers import scheduled_report

EVENTBRIDGE_FEB_1 = {
    "detail-type": "Scheduled Event",
    "source": "aws.events",
    "time": "2026-02-01T03:00:00Z",
    "detail": {},
}

TRANSACTIONS_CSV = (
    b"external_id,timestamp,amount,currency,counterparty,raw_category_hint\n"
    b"jan-1,2026-01-05T10:00:00Z,150.00,USD,Acme Corp,\n"
    b"jan-2,2026-01-31T23:00:00Z,15000.00,USD,Globex Inc,wire\n"
    b"jan-3,2026-01-20T09:00:00Z,20.00,USD,Initech,\n"
    b"feb-1,2026-02-03T10:00:00Z,999.00,USD,Umbrella,\n"
    b"dec-1,2025-12-30T10:00:00Z,555.00,USD,Hooli,\n"
)


@pytest.fixture()
def lambda_env(monkeypatch, _session_factory, test_user, db_session):
    """Handler wired to the test DB, with a January dataset ingested."""
    monkeypatch.setattr(scheduled_report, "SessionLocal", _session_factory)
    ingest_batch(
        db=db_session,
        uploaded_by_user_id=test_user.id,
        filename="jan.csv",
        content_type="text/csv",
        raw_bytes=TRANSACTIONS_CSV,
    )
    db_session.commit()
    return db_session


def _run_count(db) -> int:
    return db.scalar(select(func.count()).select_from(ReportRun))


class TestScheduledInvocation:
    def test_eventbridge_event_reports_the_previous_month(self, lambda_env):
        result = scheduled_report.handler(EVENTBRIDGE_FEB_1, None)

        assert result["status"] == "completed"
        assert result["period_start"] == "2026-01-01"
        assert result["period_end"] == "2026-01-31"
        # Only the three January transactions; Dec and Feb are out of period.
        assert result["input_transaction_count"] == 3
        assert result["reused_existing"] is False

    def test_result_is_json_serializable_as_lambda_requires(self, lambda_env):
        json.dumps(scheduled_report.handler(EVENTBRIDGE_FEB_1, None))

    def test_run_is_fully_persisted_with_audit_trail_like_an_api_run(self, lambda_env):
        result = scheduled_report.handler(EVENTBRIDGE_FEB_1, None)

        run = lambda_env.get(ReportRun, result["report_run_id"])
        lambda_env.refresh(run)
        assert run.status == ReportRunStatus.COMPLETED
        assert run.input_data_hash
        assert len(run.line_items) > 0
        assert len(run.audit_entries) > 0  # same relational audit trail as the API path
        assert run.export_json_path and run.export_csv_path and run.export_pdf_path

    def test_explicit_period_override_supports_backfill(self, lambda_env):
        result = scheduled_report.handler(
            {"period_start": "2026-02-01", "period_end": "2026-02-28"}, None
        )
        assert result["period_start"] == "2026-02-01"
        assert result["input_transaction_count"] == 1  # only feb-1

    def test_empty_period_still_produces_a_completed_report(self, lambda_env):
        result = scheduled_report.handler(
            {"period_start": "2024-01-01", "period_end": "2024-01-31"}, None
        )
        assert result["status"] == "completed"
        assert result["input_transaction_count"] == 0

    def test_lambda_context_request_id_is_accepted(self, lambda_env):
        context = SimpleNamespace(aws_request_id="req-123")
        assert scheduled_report.handler(EVENTBRIDGE_FEB_1, context)["status"] == "completed"


class TestIdempotency:
    def test_redelivered_event_does_not_create_a_duplicate_report(self, lambda_env):
        first = scheduled_report.handler(EVENTBRIDGE_FEB_1, None)
        second = scheduled_report.handler(EVENTBRIDGE_FEB_1, None)

        assert second["report_run_id"] == first["report_run_id"]
        assert second["reused_existing"] is True
        assert _run_count(lambda_env) == 1

    def test_different_period_is_not_treated_as_a_duplicate(self, lambda_env):
        scheduled_report.handler(EVENTBRIDGE_FEB_1, None)
        other = scheduled_report.handler({"time": "2026-03-01T03:00:00Z"}, None)
        assert other["reused_existing"] is False
        assert _run_count(lambda_env) == 2

    def test_a_previous_failed_run_does_not_block_the_retry(self, lambda_env, monkeypatch):
        def boom(**kwargs):
            raise RuntimeError("engine exploded")

        with monkeypatch.context() as patched:
            patched.setattr(report_service, "build_report", boom)
            with pytest.raises(RuntimeError, match="engine exploded"):
                scheduled_report.handler(EVENTBRIDGE_FEB_1, None)

        retry = scheduled_report.handler(EVENTBRIDGE_FEB_1, None)
        assert retry["status"] == "completed"
        assert retry["reused_existing"] is False

        statuses = sorted(str(s) for s in lambda_env.scalars(select(ReportRun.status)))
        assert statuses == ["completed", "failed"]


class TestFailureHandling:
    def test_pipeline_failure_is_reraised_so_lambda_reports_an_error(self, lambda_env, monkeypatch):
        monkeypatch.setattr(
            report_service, "build_report", lambda **kw: (_ for _ in ()).throw(ValueError("x"))
        )
        with pytest.raises(ValueError):
            scheduled_report.handler(EVENTBRIDGE_FEB_1, None)

        run = lambda_env.scalars(select(ReportRun)).one()
        lambda_env.refresh(run)
        assert run.status == ReportRunStatus.FAILED  # failure is auditable, not lost
        assert run.error_message

    def test_invalid_event_is_rejected_before_touching_the_database(self, lambda_env):
        with pytest.raises(ValidationError):
            scheduled_report.handler({"period_start": "2026-01-01"}, None)
        assert _run_count(lambda_env) == 0

    def test_unknown_rule_set_version_is_rejected(self, lambda_env):
        with pytest.raises(UnknownRuleSetVersionError):
            scheduled_report.handler({**EVENTBRIDGE_FEB_1, "rule_set_version": "v999"}, None)
        assert _run_count(lambda_env) == 0

    def test_session_is_closed_even_when_the_run_fails(self, lambda_env, monkeypatch):
        closed = []

        class TrackingSession:
            def __init__(self):
                from sqlalchemy.orm import sessionmaker

                self._real = sessionmaker(
                    bind=lambda_env.get_bind(), expire_on_commit=False, autoflush=False
                )()

            def __getattr__(self, name):
                return getattr(self._real, name)

            def close(self):
                closed.append(True)
                self._real.close()

        monkeypatch.setattr(scheduled_report, "SessionLocal", TrackingSession)
        monkeypatch.setattr(
            scheduled_report_service,
            "generate_report",
            lambda **kw: (_ for _ in ()).throw(RuntimeError("nope")),
        )
        with pytest.raises(RuntimeError):
            scheduled_report.handler(EVENTBRIDGE_FEB_1, None)
        assert closed == [True]


class TestServiceAccount:
    def test_runs_are_attributed_to_a_non_loginable_service_account(self, lambda_env):
        result = scheduled_report.handler(EVENTBRIDGE_FEB_1, None)

        run = lambda_env.get(ReportRun, result["report_run_id"])
        account = lambda_env.get(User, run.triggered_by_user_id)
        assert account.email == SERVICE_ACCOUNT_EMAIL
        assert account.is_active is False  # get_current_user rejects inactive users

    def test_service_account_is_created_once(self, lambda_env):
        scheduled_report.handler(EVENTBRIDGE_FEB_1, None)
        scheduled_report.handler({"time": "2026-03-01T03:00:00Z"}, None)
        count = lambda_env.scalar(
            select(func.count()).select_from(User).where(User.email == SERVICE_ACCOUNT_EMAIL)
        )
        assert count == 1

    def test_losing_the_creation_race_reuses_the_winners_account(self, lambda_env, monkeypatch):
        """Two concurrent first invocations: the loser hits the unique
        constraint on email and must adopt the account the winner created."""
        from app.infrastructure.db.repositories.user_repository import UserRepository

        scheduled_report.handler(EVENTBRIDGE_FEB_1, None)  # winner creates it
        real_get = UserRepository.get_by_email
        lookups = []

        def stale_first_lookup(self, email):
            lookups.append(email)
            return None if len(lookups) == 1 else real_get(self, email)

        monkeypatch.setattr(UserRepository, "get_by_email", stale_first_lookup)

        result = scheduled_report.handler({"time": "2026-03-01T03:00:00Z"}, None)

        assert result["status"] == "completed"
        count = lambda_env.scalar(
            select(func.count()).select_from(User).where(User.email == SERVICE_ACCOUNT_EMAIL)
        )
        assert count == 1

    def test_service_account_cannot_authenticate_through_the_api(self, client, lambda_env):
        scheduled_report.handler(EVENTBRIDGE_FEB_1, None)
        # Its password is random and unknown, so login fails outright.
        response = client.post(
            "/api/v1/auth/login",
            data={"username": SERVICE_ACCOUNT_EMAIL, "password": "anything"},
        )
        assert response.status_code == 401
