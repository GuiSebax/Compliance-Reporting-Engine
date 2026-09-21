from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReportTriggerRequest(BaseModel):
    period_start: date
    period_end: date
    rule_set_version: str | None = Field(
        default=None, description="Defaults to the current rule set version if omitted."
    )

    @model_validator(mode="after")
    def _validate_period(self) -> ReportTriggerRequest:
        if self.period_end < self.period_start:
            raise ValueError("period_end must not be before period_start")
        return self


class ReportLineItemResponse(BaseModel):
    category: str
    currency: str
    metric_name: str
    metric_value: Decimal
    transaction_count: int
    source_transaction_ids: list[str]

    model_config = ConfigDict(from_attributes=True)


class ViolationResponse(BaseModel):
    rule_id: str
    severity: str
    message: str
    transaction_external_id: str


class AuditLogEntryResponse(BaseModel):
    event_type: str
    message: str
    details: dict | None = None
    occurred_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReportSummaryResponse(BaseModel):
    id: str
    period_start: date
    period_end: date
    status: str
    rule_set_version: str
    rule_set_definition_hash: str
    input_transaction_count: int
    input_data_hash: str
    started_at: datetime
    finished_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReportDetailResponse(ReportSummaryResponse):
    line_items: list[ReportLineItemResponse]
    violations: list[ViolationResponse]
    audit_trail: list[AuditLogEntryResponse]
    export_json_available: bool
    export_csv_available: bool
    export_pdf_available: bool
