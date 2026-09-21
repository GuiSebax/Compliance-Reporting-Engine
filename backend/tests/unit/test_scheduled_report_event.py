"""Pure unit tests for the Lambda's event parsing and period policy (no DB)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from app.application.scheduled_report_service import previous_month_period
from app.lambda_handlers.scheduled_report import ScheduledReportEvent

EVENTBRIDGE_SCHEDULED_EVENT = {
    "version": "0",
    "id": "53dc4d37-cffa-4f76-80c9-8b7d4a4d2eaa",
    "detail-type": "Scheduled Event",
    "source": "aws.events",
    "account": "123456789012",
    "time": "2026-02-01T03:00:00Z",
    "region": "us-east-1",
    "resources": ["arn:aws:events:us-east-1:123456789012:rule/monthly-compliance-report"],
    "detail": {},
}


class TestPreviousMonthPeriod:
    @pytest.mark.parametrize(
        ("reference", "expected"),
        [
            (date(2026, 2, 1), (date(2026, 1, 1), date(2026, 1, 31))),
            (date(2026, 7, 15), (date(2026, 6, 1), date(2026, 6, 30))),
            (date(2026, 1, 1), (date(2025, 12, 1), date(2025, 12, 31))),  # year rollover
            (date(2026, 3, 1), (date(2026, 2, 1), date(2026, 2, 28))),
            (date(2028, 3, 1), (date(2028, 2, 1), date(2028, 2, 29))),  # leap year
            (date(2026, 5, 31), (date(2026, 4, 1), date(2026, 4, 30))),
        ],
    )
    def test_returns_full_previous_calendar_month(self, reference, expected):
        assert previous_month_period(reference) == expected


class TestEventParsing:
    def test_real_eventbridge_envelope_is_accepted_and_extras_ignored(self):
        event = ScheduledReportEvent.model_validate(EVENTBRIDGE_SCHEDULED_EVENT)
        assert event.resolve_period() == (date(2026, 1, 1), date(2026, 1, 31))

    def test_empty_event_falls_back_to_previous_month_of_now(self):
        event = ScheduledReportEvent.model_validate({})
        now = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
        assert event.resolve_period(now=now) == (date(2026, 8, 1), date(2026, 8, 31))

    def test_explicit_period_overrides_schedule_time(self):
        event = ScheduledReportEvent.model_validate(
            {
                **EVENTBRIDGE_SCHEDULED_EVENT,
                "period_start": "2025-06-01",
                "period_end": "2025-06-30",
                "rule_set_version": "v1",
            }
        )
        assert event.resolve_period() == (date(2025, 6, 1), date(2025, 6, 30))
        assert event.rule_set_version == "v1"

    def test_event_time_is_normalised_to_utc_before_picking_the_month(self):
        # 23:30 on Jan 31 in UTC-5 is already Feb 1 (04:30) in UTC, so the
        # month that just ended is January — not December.
        event = ScheduledReportEvent.model_validate({"time": "2026-01-31T23:30:00-05:00"})
        assert event.resolve_period() == (date(2026, 1, 1), date(2026, 1, 31))

    def test_naive_event_time_is_treated_as_utc(self):
        event = ScheduledReportEvent.model_validate({"time": "2026-03-01T00:00:00"})
        assert event.resolve_period() == (date(2026, 2, 1), date(2026, 2, 28))

    @pytest.mark.parametrize(
        "bad_event",
        [
            {"period_start": "2026-01-01"},  # half an override
            {"period_end": "2026-01-31"},
            {"period_start": "2026-02-01", "period_end": "2026-01-01"},  # reversed
            {"period_start": "not-a-date", "period_end": "2026-01-31"},
            {"time": "yesterday-ish"},
        ],
    )
    def test_invalid_events_are_rejected(self, bad_event):
        with pytest.raises(ValidationError):
            ScheduledReportEvent.model_validate(bad_event)
