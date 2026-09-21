"""Pure orchestration: turns a list of transactions + a rule set version
into a complete, self-contained ``ReportResult``.

This is the single function the rest of the system calls to "run the
compliance engine" — it has no I/O (no DB, no filesystem, no network) so
it can be exercised in unit tests with nothing but in-memory data,
independent of the API or persistence layers.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime

from app.domain.models.report import AuditEvent, AuditEventType, ReportResult
from app.domain.models.transaction import Transaction
from app.domain.rules.engine import RuleEngine
from app.domain.rules.rule_set import RuleSet
from app.domain.services.aggregation import aggregate_line_items


def compute_input_data_hash(transactions: list[Transaction]) -> str:
    """Deterministic fingerprint of the exact input a report run consumed.

    Sorted by ``external_id`` before hashing so the hash depends only on
    *which* transactions were fed in and their values, never on the
    incidental order they were loaded from the database in. Persisting
    this alongside a ``ReportRun`` lets anyone later verify "was this
    report really generated from this data?" without re-trusting the
    pipeline that produced it.
    """
    if not transactions:
        return hashlib.sha256(b"EMPTY_BATCH").hexdigest()

    ordered = sorted(transactions, key=lambda t: t.external_id)
    parts = [
        f"{t.external_id}|{t.timestamp.isoformat()}|{t.amount}|{t.currency}|{t.counterparty}"
        for t in ordered
    ]
    digest_input = "\n".join(parts).encode("utf-8")
    return hashlib.sha256(digest_input).hexdigest()


def build_report(
    *,
    transactions: list[Transaction],
    rule_set: RuleSet,
    period_start: date,
    period_end: date,
) -> ReportResult:
    """Run the full classify -> validate -> aggregate pipeline once.

    An empty ``transactions`` list is a valid (if unusual) input — e.g. a
    period with no recorded activity — and produces a report with zero
    line items rather than raising, so scheduled/periodic report runs
    don't need special-case handling for quiet periods.
    """
    now = datetime.now(UTC)
    audit_trail: list[AuditEvent] = [
        AuditEvent(
            event_type=AuditEventType.INGESTION_LOADED,
            message=f"Loaded {len(transactions)} transaction(s) for period.",
            occurred_at=now,
            details={"transaction_count": len(transactions)},
        )
    ]

    input_hash = compute_input_data_hash(transactions)

    engine = RuleEngine(rule_set)
    engine_result = engine.run(transactions)

    audit_trail.append(
        AuditEvent(
            event_type=AuditEventType.RULES_APPLIED,
            message=(
                f"Applied rule set '{rule_set.version}' "
                f"(hash={rule_set.definition_hash[:12]}) to "
                f"{len(engine_result.classified_transactions)} transaction(s)."
            ),
            occurred_at=datetime.now(UTC),
            details={
                "rule_set_version": rule_set.version,
                "rule_set_definition_hash": rule_set.definition_hash,
            },
        )
    )
    audit_trail.append(
        AuditEvent(
            event_type=AuditEventType.VALIDATION_COMPLETED,
            message=f"Validation raised {len(engine_result.violations)} violation(s).",
            occurred_at=datetime.now(UTC),
            details={"violation_count": len(engine_result.violations)},
        )
    )

    line_items = aggregate_line_items(list(engine_result.classified_transactions))

    audit_trail.append(
        AuditEvent(
            event_type=AuditEventType.AGGREGATION_COMPLETED,
            message=f"Produced {len(line_items)} report line item(s).",
            occurred_at=datetime.now(UTC),
            details={"line_item_count": len(line_items)},
        )
    )

    return ReportResult(
        period_start=period_start,
        period_end=period_end,
        rule_set_version=rule_set.version,
        input_data_hash=input_hash,
        input_transaction_count=len(transactions),
        generated_at=now,
        line_items=line_items,
        violations=engine_result.violations,
        audit_trail=tuple(audit_trail),
    )
