"""Base contracts for the rule engine.

Two kinds of rules exist:

- ``ClassificationRule`` looks at a transaction and, if it matches, assigns
  a category. Rules are evaluated in order per rule set; the first match
  wins so rule ordering is itself part of a rule set's versioned identity.
- ``ValidationRule`` looks at an already-classified transaction and may
  raise zero or more ``RuleViolation``s (threshold breaches, malformed
  data, inconsistent fields). Validation never blocks classification —
  a violated transaction is still reported, just flagged.

Both are plain, side-effect-free callables so they can be unit tested
directly with a bare ``Transaction`` and no other fixture.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.models.transaction import (
    RuleViolation,
    Transaction,
    TransactionCategory,
)


class ClassificationRule(ABC):
    """A single, named rule that may assign a category to a transaction."""

    #: Stable identifier persisted in the audit trail. Never rename an
    #: existing rule's id across versions — bump the rule set version and
    #: register a new rule instead, so historical report runs stay legible.
    rule_id: str

    @abstractmethod
    def classify(self, transaction: Transaction) -> TransactionCategory | None:
        """Return a category if this rule matches, else ``None``."""
        raise NotImplementedError


class ValidationRule(ABC):
    """A single, named rule that checks a classified transaction."""

    rule_id: str

    @abstractmethod
    def validate(
        self, transaction: Transaction, category: TransactionCategory
    ) -> list[RuleViolation]:
        """Return zero or more violations found for this transaction."""
        raise NotImplementedError
