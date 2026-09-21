"""Concrete classification rules for rule set ``v1``.

Rules are evaluated in the order they appear in a ``RuleSet`` and the
first match wins (see ``app.domain.rules.engine.RuleEngine``), so the
order the rules are *listed in* (``app.domain.rules.registry``) is part
of the rule set's behavior, not an implementation detail.
"""

from __future__ import annotations

from decimal import Decimal

from app.domain.models.transaction import Transaction, TransactionCategory
from app.domain.rules.base import ClassificationRule

#: Transactions at or above this amount are always flagged HIGH_VALUE,
#: regardless of any other hint, because they cross the threshold most
#: compliance regimes key large-transaction reporting off of.
HIGH_VALUE_THRESHOLD = Decimal("10000.00")

_INTERNAL_HINTS = {"internal", "internal_transfer"}
_FEE_HINTS = {"fee", "service_fee"}
_REFUND_HINTS = {"refund", "chargeback"}
_WIRE_HINTS = {"wire", "wire_transfer", "swift"}
_SUSPICIOUS_HINTS = {"suspicious", "flagged"}


def _normalized_hint(transaction: Transaction) -> str | None:
    if transaction.raw_category_hint is None:
        return None
    return transaction.raw_category_hint.strip().lower()


class SuspiciousHintRule(ClassificationRule):
    """Honors an explicit upstream flag that a transaction needs review."""

    rule_id = "classify.suspicious_hint"

    def classify(self, transaction: Transaction) -> TransactionCategory | None:
        if _normalized_hint(transaction) in _SUSPICIOUS_HINTS:
            return TransactionCategory.SUSPICIOUS
        return None


class InternalTransferRule(ClassificationRule):
    rule_id = "classify.internal_transfer"

    def classify(self, transaction: Transaction) -> TransactionCategory | None:
        if _normalized_hint(transaction) in _INTERNAL_HINTS:
            return TransactionCategory.INTERNAL_TRANSFER
        return None


class FeeRule(ClassificationRule):
    rule_id = "classify.fee"

    def classify(self, transaction: Transaction) -> TransactionCategory | None:
        if _normalized_hint(transaction) in _FEE_HINTS:
            return TransactionCategory.FEE
        return None


class RefundRule(ClassificationRule):
    """A refund is either explicitly hinted or carries a negative amount."""

    rule_id = "classify.refund"

    def classify(self, transaction: Transaction) -> TransactionCategory | None:
        if _normalized_hint(transaction) in _REFUND_HINTS or transaction.amount < 0:
            return TransactionCategory.REFUND
        return None


class HighValueRule(ClassificationRule):
    """Amount-threshold rule — deliberately placed ahead of the generic
    wire/retail rules so a large wire transfer is still surfaced as
    HIGH_VALUE for reporting purposes rather than hidden inside WIRE_TRANSFER.
    """

    rule_id = "classify.high_value_threshold"

    def classify(self, transaction: Transaction) -> TransactionCategory | None:
        if transaction.amount >= HIGH_VALUE_THRESHOLD:
            return TransactionCategory.HIGH_VALUE
        return None


class WireTransferRule(ClassificationRule):
    rule_id = "classify.wire_transfer"

    def classify(self, transaction: Transaction) -> TransactionCategory | None:
        if _normalized_hint(transaction) in _WIRE_HINTS:
            return TransactionCategory.WIRE_TRANSFER
        return None


class RetailPaymentFallbackRule(ClassificationRule):
    """Catch-all — must always be the last rule in a rule set."""

    rule_id = "classify.retail_payment_fallback"

    def classify(self, transaction: Transaction) -> TransactionCategory | None:
        return TransactionCategory.RETAIL_PAYMENT
