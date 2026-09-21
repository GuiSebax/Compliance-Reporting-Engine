// Mirrors backend/app/schemas/*.py — kept intentionally simple (plain
// interfaces, no codegen) since the surface area is small; a larger
// project would generate this from the FastAPI OpenAPI schema instead.

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in_minutes: number;
}

export interface RejectedRow {
  row_index: number;
  reason: string;
}

export interface BatchSummary {
  id: string;
  original_filename: string;
  status: string;
  row_count: number;
  accepted_row_count: number;
  rejected_row_count: number;
  created_at: string;
}

export interface BatchDetail extends BatchSummary {
  rejected_rows: RejectedRow[];
  checksum_sha256: string;
}

export interface ReportLineItem {
  category: string;
  currency: string;
  metric_name: string;
  metric_value: string;
  transaction_count: number;
  source_transaction_ids: string[];
}

export interface Violation {
  rule_id: string;
  severity: string;
  message: string;
  transaction_external_id: string;
}

export interface AuditLogEntry {
  event_type: string;
  message: string;
  details: Record<string, unknown> | null;
  occurred_at: string;
}

export interface ReportSummary {
  id: string;
  period_start: string;
  period_end: string;
  status: string;
  rule_set_version: string;
  rule_set_definition_hash: string;
  input_transaction_count: number;
  input_data_hash: string;
  started_at: string;
  finished_at: string | null;
  created_at: string;
}

export interface ReportDetail extends ReportSummary {
  line_items: ReportLineItem[];
  violations: Violation[];
  audit_trail: AuditLogEntry[];
  export_json_available: boolean;
  export_csv_available: boolean;
  export_pdf_available: boolean;
}
