"""Pure domain output of a report generation run.

These dataclasses are the contract between the rule engine / aggregation
layer and everything downstream (persistence, JSON/CSV/PDF export). They
carry no ORM or framework types so they can be constructed and asserted
against directly in unit tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from app.domain.models.transaction import RuleViolation


class AuditEventType(StrEnum):
    """Kind of event recorded in a report run's audit trail."""

    INGESTION_LOADED = "ingestion_loaded"
    RULES_APPLIED = "rules_applied"
    VALIDATION_COMPLETED = "validation_completed"
    AGGREGATION_COMPLETED = "aggregation_completed"
    REPORT_PERSISTED = "report_persisted"
    EXPORT_GENERATED = "export_generated"
    REPORT_FAILED = "report_failed"


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """One entry of the auditable trace of how a report was produced."""

    event_type: AuditEventType
    message: str
    occurred_at: datetime
    details: dict[str, str | int | float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReportLineItem:
    """One aggregated, reportable number and everything needed to trace it.

    ``category`` and ``metric_name`` together identify what was measured;
    ``source_transaction_count`` and ``source_transaction_ids`` are what
    make the number auditable — anyone can ask "which transactions produced
    this figure?" and get a direct answer instead of having to re-derive it.
    """

    category: str
    currency: str
    metric_name: str
    metric_value: Decimal
    transaction_count: int
    source_transaction_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReportResult:
    """The full, self-contained output of one report generation run.

    ``rule_set_version`` and ``input_data_hash`` are what make a report
    run reproducible and auditable after the fact: given the same
    transactions and the same rule set version, the engine is deterministic
    and will produce byte-identical line items.
    """

    period_start: date
    period_end: date
    rule_set_version: str
    input_data_hash: str
    input_transaction_count: int
    generated_at: datetime
    line_items: tuple[ReportLineItem, ...]
    violations: tuple[RuleViolation, ...]
    audit_trail: tuple[AuditEvent, ...]

    @property
    def has_critical_violations(self) -> bool:
        from app.domain.models.transaction import ViolationSeverity

        return any(v.severity == ViolationSeverity.CRITICAL for v in self.violations)
