"""Unit tests for the end-to-end pure report-building pipeline."""

from datetime import UTC, date, datetime
from decimal import Decimal

from app.domain.models.report import AuditEventType
from app.domain.models.transaction import Transaction
from app.domain.rules.registry import RULE_SET_V1
from app.domain.services.report_builder import build_report, compute_input_data_hash


def make_transaction(external_id: str, amount: str, currency: str = "USD") -> Transaction:
    return Transaction(
        external_id=external_id,
        timestamp=datetime(2026, 1, 10, tzinfo=UTC),
        amount=Decimal(amount),
        currency=currency,
        counterparty="Acme Corp",
    )


class TestInputDataHash:
    def test_hash_is_deterministic_regardless_of_input_order(self):
        tx_a = make_transaction("tx-a", "10.00")
        tx_b = make_transaction("tx-b", "20.00")
        assert compute_input_data_hash([tx_a, tx_b]) == compute_input_data_hash([tx_b, tx_a])

    def test_hash_changes_when_an_amount_changes(self):
        original = compute_input_data_hash([make_transaction("tx-a", "10.00")])
        modified = compute_input_data_hash([make_transaction("tx-a", "10.01")])
        assert original != modified

    def test_empty_batch_has_a_stable_well_known_hash(self):
        assert compute_input_data_hash([]) == compute_input_data_hash([])


class TestBuildReport:
    def test_report_is_reproducible_for_identical_input(self):
        transactions = [make_transaction("tx-1", "150.00")]
        report_a = build_report(
            transactions=transactions,
            rule_set=RULE_SET_V1,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
        report_b = build_report(
            transactions=transactions,
            rule_set=RULE_SET_V1,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
        assert report_a.input_data_hash == report_b.input_data_hash
        assert report_a.line_items == report_b.line_items

    def test_report_records_rule_set_version_and_input_hash(self):
        transactions = [make_transaction("tx-1", "150.00")]
        report = build_report(
            transactions=transactions,
            rule_set=RULE_SET_V1,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
        assert report.rule_set_version == "v1"
        assert report.input_data_hash == compute_input_data_hash(transactions)
        assert report.input_transaction_count == 1

    def test_audit_trail_covers_every_pipeline_stage(self):
        report = build_report(
            transactions=[make_transaction("tx-1", "10.00")],
            rule_set=RULE_SET_V1,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
        event_types = {event.event_type for event in report.audit_trail}
        assert event_types == {
            AuditEventType.INGESTION_LOADED,
            AuditEventType.RULES_APPLIED,
            AuditEventType.VALIDATION_COMPLETED,
            AuditEventType.AGGREGATION_COMPLETED,
        }

    def test_empty_transaction_list_produces_an_empty_but_valid_report(self):
        report = build_report(
            transactions=[],
            rule_set=RULE_SET_V1,
            period_start=date(2026, 2, 1),
            period_end=date(2026, 2, 28),
        )
        assert report.line_items == ()
        assert report.violations == ()
        assert report.input_transaction_count == 0
        assert report.has_critical_violations is False

    def test_has_critical_violations_reflects_severity(self):
        report = build_report(
            transactions=[make_transaction("tx-1", "10.00", currency="INVALID")],
            rule_set=RULE_SET_V1,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
        assert report.has_critical_violations is True
