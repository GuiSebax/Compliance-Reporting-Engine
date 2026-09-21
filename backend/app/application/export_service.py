"""Turns a domain ``ReportResult`` into JSON/CSV/PDF files on disk and
mirrors them to S3 (best-effort — see ``app.infrastructure.storage.s3_client``).

Export format is intentionally generated from the *same* ``ReportResult``
object for all three formats, so JSON/CSV/PDF can never drift from each
other — there is exactly one source of truth for "what does this report
say", and each exporter is just a different rendering of it.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.config import get_settings
from app.domain.models.report import ReportResult
from app.infrastructure.logging import get_logger
from app.infrastructure.storage import s3_client

logger = get_logger(__name__)


class _DecimalEncoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if isinstance(o, Decimal):
            return str(o)
        return super().default(o)


def report_result_to_dict(report: ReportResult) -> dict:
    payload = asdict(report)
    payload["period_start"] = report.period_start.isoformat()
    payload["period_end"] = report.period_end.isoformat()
    payload["generated_at"] = report.generated_at.isoformat()
    for event in payload["audit_trail"]:
        event["occurred_at"] = event["occurred_at"].isoformat()
    return payload


def _report_dir(report_run_id: str) -> Path:
    settings = get_settings()
    directory = Path(settings.reports_local_dir) / report_run_id
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def write_json_export(report: ReportResult, report_run_id: str) -> str:
    directory = _report_dir(report_run_id)
    path = directory / "report.json"
    payload = report_result_to_dict(report)
    path.write_text(json.dumps(payload, cls=_DecimalEncoder, indent=2), encoding="utf-8")
    return str(path)


def write_csv_export(report: ReportResult, report_run_id: str) -> str:
    directory = _report_dir(report_run_id)
    path = directory / "report.csv"
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["category", "currency", "metric_name", "metric_value", "transaction_count"])
    for item in report.line_items:
        writer.writerow(
            [
                item.category,
                item.currency,
                item.metric_name,
                item.metric_value,
                item.transaction_count,
            ]
        )
    path.write_text(buffer.getvalue(), encoding="utf-8")
    return str(path)


def write_pdf_export(report: ReportResult, report_run_id: str) -> str:
    directory = _report_dir(report_run_id)
    path = directory / "report.pdf"

    doc = SimpleDocTemplate(str(path), pagesize=letter)
    styles = getSampleStyleSheet()
    elements: list = [
        Paragraph("Compliance Report", styles["Title"]),
        Paragraph(
            f"Period: {report.period_start.isoformat()} to {report.period_end.isoformat()}",
            styles["Normal"],
        ),
        Paragraph(f"Rule set version: {report.rule_set_version}", styles["Normal"]),
        Paragraph(f"Input data hash: {report.input_data_hash}", styles["Normal"]),
        Paragraph(f"Input transaction count: {report.input_transaction_count}", styles["Normal"]),
        Paragraph(f"Generated at: {report.generated_at.isoformat()}", styles["Normal"]),
        Spacer(1, 16),
        Paragraph("Aggregated line items", styles["Heading2"]),
    ]

    table_data = [["Category", "Currency", "Metric", "Value", "Tx Count"]]
    for item in report.line_items:
        table_data.append(
            [
                item.category,
                item.currency,
                item.metric_name,
                str(item.metric_value),
                str(item.transaction_count),
            ]
        )
    table = Table(table_data, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")]),
            ]
        )
    )
    elements.append(table)

    if report.violations:
        elements.append(Spacer(1, 16))
        elements.append(Paragraph(f"Violations ({len(report.violations)})", styles["Heading2"]))
        violation_data = [["Rule", "Severity", "Transaction", "Message"]]
        for v in report.violations[:200]:  # cap for a sane page count
            violation_data.append([v.rule_id, v.severity, v.transaction_external_id, v.message])
        violation_table = Table(violation_data, repeatRows=1)
        violation_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#7f1d1d")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTSIZE", (0, 0), (-1, -1), 7),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ]
            )
        )
        elements.append(violation_table)

    doc.build(elements)
    return str(path)


def upload_all_to_s3(
    *, report_run_id: str, json_path: str, csv_path: str, pdf_path: str
) -> dict[str, str | None]:
    keys = {}
    for label, local_path in (("json", json_path), ("csv", csv_path), ("pdf", pdf_path)):
        key = f"reports/{report_run_id}/report.{label}"
        keys[f"s3_{label}_key"] = s3_client.upload_file(local_path=local_path, key=key)
    return keys
