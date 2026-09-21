"""Concrete validation rules for rule set ``v1``.

Validation runs *after* classification and never changes a transaction's
category — it only ever appends ``RuleViolation``s. This keeps the two
concerns independent and separately testable: classification answers
"what is this?", validation answers "is this trustworthy/compliant?".
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from app.domain.models.transaction import (
    RuleViolation,
    Transaction,
    TransactionCategory,
    ViolationSeverity,
)
from app.domain.rules.base import ValidationRule
from app.domain.rules.classification_rules import HIGH_VALUE_THRESHOLD

_ISO_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


class CurrencyFormatRule(ValidationRule):
    """Currency must be a 3-letter ISO-4217-shaped code (format check)."""

    rule_id = "validate.currency_format"

    def validate(
        self, transaction: Transaction, category: TransactionCategory
    ) -> list[RuleViolation]:
        if not _ISO_CURRENCY_RE.match(transaction.currency):
            return [
                RuleViolation(
                    rule_id=self.rule_id,
                    severity=ViolationSeverity.CRITICAL,
                    message=(
                        f"Currency '{transaction.currency}' is not a valid "
                        "3-letter ISO-4217 code."
                    ),
                    transaction_external_id=transaction.external_id,
                )
            ]
        return []


class NonRefundPositiveAmountRule(ValidationRule):
    """Any transaction not classified as a refund should carry a positive
    amount — a negative amount elsewhere in the ledger is a consistency
    red flag (data entry error or miscategorized refund)."""

    rule_id = "validate.non_refund_positive_amount"

    def validate(
        self, transaction: Transaction, category: TransactionCategory
    ) -> list[RuleViolation]:
        if category != TransactionCategory.REFUND and transaction.amount <= 0:
            return [
                RuleViolation(
                    rule_id=self.rule_id,
                    severity=ViolationSeverity.WARNING,
                    message=(
                        f"Transaction classified as '{category}' has a "
                        f"non-positive amount ({transaction.amount})."
                    ),
                    transaction_external_id=transaction.external_id,
                )
            ]
        return []


class HighValueCounterpartyRule(ValidationRule):
    """Transactions at/above the high-value threshold must identify a
    counterparty — most reporting regimes require this for large-value
    movements, so a missing counterparty here is a compliance-blocking
    (CRITICAL) issue rather than a mere data-quality warning."""

    rule_id = "validate.high_value_requires_counterparty"

    def validate(
        self, transaction: Transaction, category: TransactionCategory
    ) -> list[RuleViolation]:
        if transaction.amount >= HIGH_VALUE_THRESHOLD and not transaction.counterparty.strip():
            return [
                RuleViolation(
                    rule_id=self.rule_id,
                    severity=ViolationSeverity.CRITICAL,
                    message=(
                        "Transaction at/above the high-value threshold "
                        f"({HIGH_VALUE_THRESHOLD}) is missing a counterparty."
                    ),
                    transaction_external_id=transaction.external_id,
                )
            ]
        return []


class NoFutureDatedTransactionRule(ValidationRule):
    """A transaction timestamped in the future is almost always a data
    quality issue (clock skew, bad import) rather than a real event."""

    rule_id = "validate.no_future_dated_transaction"

    def validate(
        self, transaction: Transaction, category: TransactionCategory
    ) -> list[RuleViolation]:
        now = datetime.now(UTC)
        ts = transaction.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        if ts > now:
            return [
                RuleViolation(
                    rule_id=self.rule_id,
                    severity=ViolationSeverity.WARNING,
                    message=f"Transaction timestamp {ts.isoformat()} is in the future.",
                    transaction_external_id=transaction.external_id,
                )
            ]
        return []
