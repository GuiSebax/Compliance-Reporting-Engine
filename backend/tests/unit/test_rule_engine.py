"""Unit tests for the rule engine — the core, isolated business logic.

These tests exercise ``app.domain`` exclusively: no FastAPI, no database,
no filesystem. That is the whole point of keeping the rule engine pure —
every one of these cases runs in milliseconds and needs no fixtures
beyond plain Python objects.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.domain.models.transaction import Transaction, TransactionCategory, ViolationSeverity
from app.domain.rules.classification_rules import HIGH_VALUE_THRESHOLD
from app.domain.rules.engine import RuleEngine
from app.domain.rules.registry import RULE_SET_V1


def make_transaction(
    external_id: str = "tx-1",
    amount: Decimal = Decimal("100.00"),
    currency: str = "USD",
    counterparty: str = "Acme Corp",
    raw_category_hint: str | None = None,
    timestamp: datetime | None = None,
) -> Transaction:
    return Transaction(
        external_id=external_id,
        timestamp=timestamp or datetime(2026, 1, 15, tzinfo=UTC),
        amount=amount,
        currency=currency,
        counterparty=counterparty,
        raw_category_hint=raw_category_hint,
    )


@pytest.fixture
def engine() -> RuleEngine:
    return RuleEngine(RULE_SET_V1)


class TestClassification:
    def test_retail_payment_is_the_default_fallback(self, engine: RuleEngine):
        tx = make_transaction(amount=Decimal("50.00"))
        result = engine.run([tx])
        assert result.classified_transactions[0].category == TransactionCategory.RETAIL_PAYMENT

    def test_wire_hint_classifies_as_wire_transfer(self, engine: RuleEngine):
        tx = make_transaction(amount=Decimal("500.00"), raw_category_hint="wire")
        result = engine.run([tx])
        assert result.classified_transactions[0].category == TransactionCategory.WIRE_TRANSFER

    def test_internal_hint_classifies_as_internal_transfer(self, engine: RuleEngine):
        tx = make_transaction(raw_category_hint="internal_transfer")
        result = engine.run([tx])
        assert result.classified_transactions[0].category == TransactionCategory.INTERNAL_TRANSFER

    def test_negative_amount_classifies_as_refund_without_hint(self, engine: RuleEngine):
        tx = make_transaction(amount=Decimal("-25.00"))
        result = engine.run([tx])
        assert result.classified_transactions[0].category == TransactionCategory.REFUND

    def test_fee_hint_classifies_as_fee(self, engine: RuleEngine):
        tx = make_transaction(amount=Decimal("2.50"), raw_category_hint="fee")
        result = engine.run([tx])
        assert result.classified_transactions[0].category == TransactionCategory.FEE

    def test_suspicious_hint_wins_even_with_other_signals(self, engine: RuleEngine):
        # Amount is also over the high-value threshold, but the explicit
        # suspicious flag must take priority (it's first in rule order).
        tx = make_transaction(amount=Decimal("50000.00"), raw_category_hint="suspicious")
        result = engine.run([tx])
        assert result.classified_transactions[0].category == TransactionCategory.SUSPICIOUS

    def test_high_value_overrides_generic_wire_classification(self, engine: RuleEngine):
        tx = make_transaction(amount=HIGH_VALUE_THRESHOLD, raw_category_hint="wire")
        result = engine.run([tx])
        assert result.classified_transactions[0].category == TransactionCategory.HIGH_VALUE

    def test_applied_rule_id_is_recorded_for_traceability(self, engine: RuleEngine):
        tx = make_transaction(raw_category_hint="fee")
        result = engine.run([tx])
        assert result.classified_transactions[0].applied_rule_ids == ("classify.fee",)

    @pytest.mark.parametrize(
        "amount,expected_category",
        [
            (HIGH_VALUE_THRESHOLD - Decimal("0.01"), TransactionCategory.RETAIL_PAYMENT),
            (HIGH_VALUE_THRESHOLD, TransactionCategory.HIGH_VALUE),
            (HIGH_VALUE_THRESHOLD + Decimal("0.01"), TransactionCategory.HIGH_VALUE),
        ],
    )
    def test_high_value_threshold_boundary_is_inclusive(
        self, engine: RuleEngine, amount: Decimal, expected_category: TransactionCategory
    ):
        """The threshold itself must classify as HIGH_VALUE (>=), not just
        strictly-above amounts — an off-by-one here would let exactly-at-
        threshold transactions slip past compliance reporting."""
        tx = make_transaction(amount=amount, counterparty="Acme Corp")
        result = engine.run([tx])
        assert result.classified_transactions[0].category == expected_category


class TestValidation:
    def test_valid_transaction_raises_no_violations(self, engine: RuleEngine):
        tx = make_transaction()
        result = engine.run([tx])
        assert result.violations == ()

    def test_invalid_currency_format_raises_critical_violation(self, engine: RuleEngine):
        tx = make_transaction(currency="US")
        result = engine.run([tx])
        assert len(result.violations) == 1
        assert result.violations[0].rule_id == "validate.currency_format"
        assert result.violations[0].severity == ViolationSeverity.CRITICAL

    def test_lowercase_currency_is_rejected(self, engine: RuleEngine):
        tx = make_transaction(currency="usd")
        result = engine.run([tx])
        assert any(v.rule_id == "validate.currency_format" for v in result.violations)

    def test_zero_amount_non_refund_raises_warning(self, engine: RuleEngine):
        tx = make_transaction(amount=Decimal("0.00"))
        result = engine.run([tx])
        assert any(v.rule_id == "validate.non_refund_positive_amount" for v in result.violations)

    def test_refund_with_negative_amount_raises_no_positive_amount_violation(
        self, engine: RuleEngine
    ):
        tx = make_transaction(amount=Decimal("-10.00"), raw_category_hint="refund")
        result = engine.run([tx])
        assert not any(
            v.rule_id == "validate.non_refund_positive_amount" for v in result.violations
        )

    def test_high_value_without_counterparty_raises_critical_violation(self, engine: RuleEngine):
        tx = make_transaction(amount=HIGH_VALUE_THRESHOLD, counterparty="   ")
        result = engine.run([tx])
        assert any(
            v.rule_id == "validate.high_value_requires_counterparty"
            and v.severity == ViolationSeverity.CRITICAL
            for v in result.violations
        )

    def test_future_dated_transaction_raises_warning(self, engine: RuleEngine):
        future = datetime.now(UTC) + timedelta(days=5)
        tx = make_transaction(timestamp=future)
        result = engine.run([tx])
        assert any(v.rule_id == "validate.no_future_dated_transaction" for v in result.violations)

    def test_violation_carries_the_offending_transaction_id(self, engine: RuleEngine):
        tx = make_transaction(external_id="tx-bad-currency", currency="XX")
        result = engine.run([tx])
        assert result.violations[0].transaction_external_id == "tx-bad-currency"


class TestEmptyBatch:
    def test_empty_batch_produces_no_classifications_or_violations(self, engine: RuleEngine):
        result = engine.run([])
        assert result.classified_transactions == ()
        assert result.violations == ()

    def test_engine_does_not_raise_on_empty_input(self, engine: RuleEngine):
        # Should complete without error — periodic report runs must not
        # crash just because a period had zero recorded transactions.
        result = engine.run([])
        assert result is not None


class TestDeterminism:
    def test_same_input_produces_identical_classification_output(self, engine: RuleEngine):
        tx = make_transaction(external_id="tx-det", amount=Decimal("999.99"))
        result_a = engine.run([tx])
        result_b = engine.run([tx])
        assert result_a.classified_transactions == result_b.classified_transactions
        assert result_a.violations == result_b.violations
