"""Registry of every rule set version the engine knows how to run.

New rule behavior is added by registering a *new* version here (e.g.
``v2``) rather than mutating ``v1`` in place — existing ``ReportRun``
rows reference a version string, so mutating a released rule set in
place would silently change the meaning of past reports.
"""

from __future__ import annotations

from app.domain.rules.classification_rules import (
    FeeRule,
    HighValueRule,
    InternalTransferRule,
    RefundRule,
    RetailPaymentFallbackRule,
    SuspiciousHintRule,
    WireTransferRule,
)
from app.domain.rules.rule_set import RuleSet
from app.domain.rules.validation_rules import (
    CurrencyFormatRule,
    HighValueCounterpartyRule,
    NoFutureDatedTransactionRule,
    NonRefundPositiveAmountRule,
)

RULE_SET_V1 = RuleSet(
    version="v1",
    description="Initial classification and validation rule set.",
    classification_rules=(
        SuspiciousHintRule(),
        InternalTransferRule(),
        FeeRule(),
        RefundRule(),
        HighValueRule(),
        WireTransferRule(),
        RetailPaymentFallbackRule(),  # must stay last: unconditional catch-all
    ),
    validation_rules=(
        CurrencyFormatRule(),
        NonRefundPositiveAmountRule(),
        HighValueCounterpartyRule(),
        NoFutureDatedTransactionRule(),
    ),
)

_REGISTRY: dict[str, RuleSet] = {
    RULE_SET_V1.version: RULE_SET_V1,
}

#: The version used when a report is triggered without an explicit choice.
DEFAULT_RULE_SET_VERSION = RULE_SET_V1.version


def get_rule_set(version: str) -> RuleSet:
    try:
        return _REGISTRY[version]
    except KeyError as exc:
        available = ", ".join(sorted(_REGISTRY))
        raise ValueError(
            f"Unknown rule set version '{version}'. Available versions: {available}."
        ) from exc


def list_rule_set_versions() -> list[str]:
    return sorted(_REGISTRY)
