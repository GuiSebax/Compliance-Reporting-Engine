"""A versioned, ordered collection of classification and validation rules.

A ``RuleSet`` is the unit of auditability for "which rules produced this
report": every ``ReportRun`` persists the ``version`` string plus
``definition_hash`` of the rule set that ran, so a report generated last
quarter can always be explained even after the rule catalog has evolved.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from app.domain.rules.base import ClassificationRule, ValidationRule


@dataclass(frozen=True, slots=True)
class RuleSet:
    version: str
    description: str
    classification_rules: tuple[ClassificationRule, ...]
    validation_rules: tuple[ValidationRule, ...]

    @property
    def definition_hash(self) -> str:
        """Deterministic fingerprint of rule identities and their order.

        Two rule sets with the same rules in the same order always hash
        the same; reordering, adding, or removing a rule changes the hash.
        This lets the audit trail detect "the code says v1 but the rules
        that actually ran don't match the v1 we remember" drift.
        """
        rule_ids = [r.rule_id for r in self.classification_rules] + [
            r.rule_id for r in self.validation_rules
        ]
        digest_input = "|".join(rule_ids).encode("utf-8")
        return hashlib.sha256(digest_input).hexdigest()


@dataclass(frozen=True, slots=True)
class RuleSetMetadata:
    """Lightweight, serializable summary of a rule set for API responses."""

    version: str
    description: str
    definition_hash: str
    classification_rule_ids: tuple[str, ...] = field(default_factory=tuple)
    validation_rule_ids: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_rule_set(cls, rule_set: RuleSet) -> RuleSetMetadata:
        return cls(
            version=rule_set.version,
            description=rule_set.description,
            definition_hash=rule_set.definition_hash,
            classification_rule_ids=tuple(r.rule_id for r in rule_set.classification_rules),
            validation_rule_ids=tuple(r.rule_id for r in rule_set.validation_rules),
        )
