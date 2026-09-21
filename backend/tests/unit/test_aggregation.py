"""Unit tests for the pandas-backed aggregation step."""

from datetime import UTC, datetime
from decimal import Decimal

from app.domain.models.transaction import ClassifiedTransaction, Transaction, TransactionCategory
from app.domain.services.aggregation import aggregate_line_items


def classified(
    external_id: str, amount: str, category: TransactionCategory, currency: str = "USD"
) -> ClassifiedTransaction:
    return ClassifiedTransaction(
        transaction=Transaction(
            external_id=external_id,
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            amount=Decimal(amount),
            currency=currency,
            counterparty="Acme",
        ),
        category=category,
        applied_rule_ids=("classify.retail_payment_fallback",),
    )


class TestAggregation:
    def test_empty_input_produces_no_line_items(self):
        assert aggregate_line_items([]) == ()

    def test_totals_are_computed_with_decimal_precision(self):
        items = [
            classified("tx-1", "10.10", TransactionCategory.RETAIL_PAYMENT),
            classified("tx-2", "20.20", TransactionCategory.RETAIL_PAYMENT),
        ]
        line_items = aggregate_line_items(items)
        total = next(li for li in line_items if li.metric_name == "total_amount")
        # 10.10 + 20.20 must be exactly 30.30 — a float sum would drift
        # (0.1 + 0.2 == 0.30000000000000004 in binary floating point).
        assert total.metric_value == Decimal("30.30")

    def test_categories_are_not_mixed_together(self):
        items = [
            classified("tx-1", "100.00", TransactionCategory.RETAIL_PAYMENT),
            classified("tx-2", "100.00", TransactionCategory.FEE),
        ]
        line_items = aggregate_line_items(items)
        retail_total = next(
            li
            for li in line_items
            if li.category == "retail_payment" and li.metric_name == "total_amount"
        )
        fee_total = next(
            li for li in line_items if li.category == "fee" and li.metric_name == "total_amount"
        )
        assert retail_total.metric_value == Decimal("100.00")
        assert fee_total.metric_value == Decimal("100.00")

    def test_currencies_are_not_mixed_together(self):
        items = [
            classified("tx-1", "100.00", TransactionCategory.RETAIL_PAYMENT, currency="USD"),
            classified("tx-2", "100.00", TransactionCategory.RETAIL_PAYMENT, currency="EUR"),
        ]
        line_items = aggregate_line_items(items)
        totals = {
            (li.currency): li.metric_value for li in line_items if li.metric_name == "total_amount"
        }
        assert totals == {"USD": Decimal("100.00"), "EUR": Decimal("100.00")}

    def test_source_transaction_ids_are_preserved_for_traceability(self):
        items = [
            classified("tx-1", "10.00", TransactionCategory.RETAIL_PAYMENT),
            classified("tx-2", "15.00", TransactionCategory.RETAIL_PAYMENT),
        ]
        line_items = aggregate_line_items(items)
        total = next(li for li in line_items if li.metric_name == "total_amount")
        assert set(total.source_transaction_ids) == {"tx-1", "tx-2"}

    def test_transaction_count_metric_matches_group_size(self):
        items = [
            classified("tx-1", "10.00", TransactionCategory.FEE),
            classified("tx-2", "5.00", TransactionCategory.FEE),
            classified("tx-3", "5.00", TransactionCategory.FEE),
        ]
        line_items = aggregate_line_items(items)
        count_item = next(li for li in line_items if li.metric_name == "transaction_count")
        assert count_item.metric_value == Decimal(3)
        assert count_item.transaction_count == 3

    def test_min_and_max_are_correct(self):
        items = [
            classified("tx-1", "5.00", TransactionCategory.RETAIL_PAYMENT),
            classified("tx-2", "50.00", TransactionCategory.RETAIL_PAYMENT),
            classified("tx-3", "25.00", TransactionCategory.RETAIL_PAYMENT),
        ]
        line_items = aggregate_line_items(items)
        min_item = next(li for li in line_items if li.metric_name == "min_amount")
        max_item = next(li for li in line_items if li.metric_name == "max_amount")
        assert min_item.metric_value == Decimal("5.00")
        assert max_item.metric_value == Decimal("50.00")
