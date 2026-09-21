"""Aggregates classified transactions into auditable report line items.

Grouping (via pandas, so this scales to the thousands-of-rows batches the
engine is meant to handle) is done by ``(category, currency)`` — mixing
currencies in a single sum would produce a meaningless number, so currency
is part of the grouping key rather than being dropped or averaged away.

Sums/averages/min/max are computed with Python's ``Decimal`` arithmetic
(never ``float``) to avoid introducing binary floating-point rounding
error into numbers that end up in a compliance report. pandas is used
only for the grouping/indexing machinery, not for the arithmetic itself.
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from app.domain.models.report import ReportLineItem
from app.domain.models.transaction import ClassifiedTransaction

_METRIC_TOTAL = "total_amount"
_METRIC_AVERAGE = "average_amount"
_METRIC_MIN = "min_amount"
_METRIC_MAX = "max_amount"
_METRIC_COUNT = "transaction_count"


def aggregate_line_items(
    classified_transactions: list[ClassifiedTransaction],
) -> tuple[ReportLineItem, ...]:
    """Build one ``ReportLineItem`` per (category, currency, metric)."""
    if not classified_transactions:
        return ()

    frame = pd.DataFrame(
        {
            "external_id": [c.transaction.external_id for c in classified_transactions],
            "category": [str(c.category) for c in classified_transactions],
            "currency": [c.transaction.currency for c in classified_transactions],
            "amount": [c.transaction.amount for c in classified_transactions],
        }
    )

    line_items: list[ReportLineItem] = []

    for (category, currency), group in frame.groupby(["category", "currency"], sort=True):
        amounts: list[Decimal] = list(group["amount"])
        transaction_ids: tuple[str, ...] = tuple(group["external_id"])
        count = len(amounts)
        total = sum(amounts, start=Decimal("0"))
        average = (total / count) if count else Decimal("0")

        metrics: dict[str, Decimal] = {
            _METRIC_TOTAL: total,
            _METRIC_AVERAGE: average,
            _METRIC_MIN: min(amounts),
            _METRIC_MAX: max(amounts),
            _METRIC_COUNT: Decimal(count),
        }

        for metric_name, metric_value in metrics.items():
            line_items.append(
                ReportLineItem(
                    category=category,
                    currency=currency,
                    metric_name=metric_name,
                    metric_value=metric_value,
                    transaction_count=count,
                    source_transaction_ids=transaction_ids,
                )
            )

    return tuple(line_items)
