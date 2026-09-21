"""Request/response DTOs for batch ingestion.

``TransactionRowSchema`` is the syntactic validation gate: it checks that
each raw row *has the right shape* (types, required fields present,
amount parses as an exact decimal). It deliberately does not know about
business rules like threshold amounts or currency-code correctness —
that is the rule engine's job (see ``app.domain.rules``).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TransactionRowSchema(BaseModel):
    """Syntactic validation only. Deliberately permissive on ``currency``
    and ``counterparty``:

    - ``currency`` must be present and reasonably short, but whether it is
      a valid 3-letter ISO-4217 code is treated as a *business* rule, not
      a shape rule — enforced by ``app.domain.rules.validation_rules.
      CurrencyFormatRule`` at report-generation time instead.
    - ``counterparty`` may be an empty string at ingestion — whether a
      missing counterparty is acceptable depends on the transaction
      amount (mandatory only above the high-value threshold), which is a
      business rule (``HighValueCounterpartyRule``), not a shape rule.

    Keeping shape and business validation separate means a Pydantic
    validation error always means "malformed input" and a rule violation
    always means "well-formed input that fails a business rule".
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    external_id: str = Field(min_length=1, max_length=255)
    timestamp: datetime
    amount: Decimal
    currency: str = Field(min_length=1, max_length=10)
    counterparty: str = Field(default="", max_length=255)
    raw_category_hint: str | None = Field(default=None, max_length=50)
    metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("amount", mode="before")
    @classmethod
    def _parse_amount(cls, value: object) -> object:
        if isinstance(value, float):
            # Reject silently-imprecise float input outright rather than
            # accepting it and rounding later — force the caller (CSV/JSON
            # parser) to supply a string/int that converts to Decimal exactly.
            raise ValueError(
                "amount must be provided as a string or integer, not a float, "
                "to avoid floating-point precision loss"
            )
        if isinstance(value, str):
            try:
                Decimal(value)
            except InvalidOperation as exc:
                raise ValueError(f"'{value}' is not a valid decimal amount") from exc
        return value


class RejectedRow(BaseModel):
    row_index: int
    reason: str


class BatchResponse(BaseModel):
    id: str
    original_filename: str
    status: str
    row_count: int
    accepted_row_count: int
    rejected_row_count: int
    rejected_rows: list[RejectedRow] = Field(default_factory=list)
    checksum_sha256: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BatchSummary(BaseModel):
    id: str
    original_filename: str
    status: str
    row_count: int
    accepted_row_count: int
    rejected_row_count: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
