"""Pure domain representation of a financial transaction.

This module has zero dependency on FastAPI, SQLAlchemy or any I/O
framework on purpose: the rule engine that consumes it must be testable
and reasoned about in complete isolation from the web/API/DB layers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class TransactionCategory(StrEnum):
    """Category assigned by the classification rules.

    UNCLASSIFIED is the state of every transaction before the rule engine
    runs; it should never appear in a finished report.
    """

    UNCLASSIFIED = "unclassified"
    RETAIL_PAYMENT = "retail_payment"
    WIRE_TRANSFER = "wire_transfer"
    INTERNAL_TRANSFER = "internal_transfer"
    REFUND = "refund"
    FEE = "fee"
    HIGH_VALUE = "high_value"
    SUSPICIOUS = "suspicious"


class ViolationSeverity(StrEnum):
    """Severity of a rule violation raised against a transaction."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class Transaction:
    """A single financial movement, already parsed and type-checked.

    ``external_id`` is whatever identifier the source system used (invoice
    number, payment reference, etc.) and is kept purely for traceability;
    it is not assumed to be unique across batches.
    """

    external_id: str
    timestamp: datetime
    amount: Decimal
    currency: str
    counterparty: str
    raw_category_hint: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RuleViolation:
    """A single rule failure raised while evaluating one transaction."""

    rule_id: str
    severity: ViolationSeverity
    message: str
    transaction_external_id: str


@dataclass(frozen=True, slots=True)
class ClassifiedTransaction:
    """A transaction after classification rules have run against it."""

    transaction: Transaction
    category: TransactionCategory
    applied_rule_ids: tuple[str, ...]
