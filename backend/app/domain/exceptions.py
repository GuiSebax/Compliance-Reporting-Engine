"""Domain-level exceptions.

These are raised by pure domain code and are framework-agnostic; the API
layer (``app/api``) is responsible for catching them and translating them
into the appropriate HTTP response.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for all domain-layer errors."""


class InvalidTransactionRowError(DomainError):
    """Raised when a single raw input row cannot be turned into a
    ``Transaction`` (missing/malformed field). Carries the row index so
    ingestion can report exactly which line of the upload failed."""

    def __init__(self, row_index: int, reason: str):
        self.row_index = row_index
        self.reason = reason
        super().__init__(f"Row {row_index}: {reason}")


class UnknownRuleSetVersionError(DomainError):
    """Raised when a report is requested against a rule set version that
    is not registered in ``app.domain.rules.registry``."""
