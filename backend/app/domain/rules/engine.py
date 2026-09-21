"""The rule engine: runs a ``RuleSet`` against a batch of transactions.

Deliberately a thin, deterministic loop — all the actual decision logic
lives in the individual rule classes so it can be unit tested rule by
rule. The engine's own job is just to guarantee two invariants:

1. Every transaction ends up classified (the fallback rule guarantees
   this — ``EngineResult`` never contains an ``UNCLASSIFIED`` entry).
2. Validation always runs against the *assigned* category, so a
   violation message always reflects what the transaction was actually
   reported as.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.models.transaction import (
    ClassifiedTransaction,
    RuleViolation,
    Transaction,
    TransactionCategory,
)
from app.domain.rules.rule_set import RuleSet


@dataclass(frozen=True, slots=True)
class EngineResult:
    classified_transactions: tuple[ClassifiedTransaction, ...]
    violations: tuple[RuleViolation, ...]


class RuleEngine:
    def __init__(self, rule_set: RuleSet):
        self._rule_set = rule_set

    @property
    def rule_set(self) -> RuleSet:
        return self._rule_set

    def run(self, transactions: list[Transaction]) -> EngineResult:
        classified: list[ClassifiedTransaction] = []
        violations: list[RuleViolation] = []

        for transaction in transactions:
            category, applied_rule_ids = self._classify(transaction)
            classified.append(
                ClassifiedTransaction(
                    transaction=transaction,
                    category=category,
                    applied_rule_ids=applied_rule_ids,
                )
            )
            violations.extend(self._validate(transaction, category))

        return EngineResult(
            classified_transactions=tuple(classified),
            violations=tuple(violations),
        )

    def _classify(self, transaction: Transaction) -> tuple[TransactionCategory, tuple[str, ...]]:
        for rule in self._rule_set.classification_rules:
            category = rule.classify(transaction)
            if category is not None:
                return category, (rule.rule_id,)
        # Unreachable as long as a rule set ends in an unconditional
        # fallback rule; surfaced explicitly rather than silently
        # defaulting, so a misconfigured rule set fails loudly.
        raise RuntimeError(
            f"No classification rule in rule set '{self._rule_set.version}' matched "
            f"transaction '{transaction.external_id}'. Every rule set must end in an "
            "unconditional fallback rule."
        )

    def _validate(
        self, transaction: Transaction, category: TransactionCategory
    ) -> list[RuleViolation]:
        violations: list[RuleViolation] = []
        for rule in self._rule_set.validation_rules:
            violations.extend(rule.validate(transaction, category))
        return violations
