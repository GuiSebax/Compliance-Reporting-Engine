import json

CSV_CONTENT = (
    b"external_id,timestamp,amount,currency,counterparty,raw_category_hint\n"
    b"tx-1,2026-01-05T10:00:00Z,150.00,USD,Acme Corp,\n"
    b"tx-2,2026-01-06T11:00:00Z,15000.00,USD,Globex Inc,wire\n"
    b"tx-3,2026-01-07T12:00:00Z,-20.00,USD,Acme Corp,refund\n"
)


def _upload(client, auth_headers, content: bytes = CSV_CONTENT):
    response = client.post(
        "/api/v1/batches/upload",
        headers=auth_headers,
        files={"file": ("transactions.csv", content, "text/csv")},
    )
    assert response.status_code == 201, response.text
    return response.json()


class TestTriggerReport:
    def test_report_generation_produces_line_items_and_audit_trail(self, client, auth_headers):
        _upload(client, auth_headers)

        response = client.post(
            "/api/v1/reports",
            headers=auth_headers,
            json={"period_start": "2026-01-01", "period_end": "2026-01-31"},
        )
        assert response.status_code == 201, response.text
        body = response.json()

        assert body["status"] == "completed"
        assert body["rule_set_version"] == "v1"
        assert body["input_transaction_count"] == 3
        assert len(body["input_data_hash"]) == 64
        assert len(body["line_items"]) > 0
        assert len(body["audit_trail"]) >= 4
        # tx-2 is HIGH_VALUE (>= 10000) and has a counterparty, so it should
        # not raise a violation; the report must still be well-formed.
        assert body["export_json_available"] is True
        assert body["export_csv_available"] is True
        assert body["export_pdf_available"] is True

    def test_report_for_period_with_no_transactions_is_still_valid(self, client, auth_headers):
        _upload(client, auth_headers)

        response = client.post(
            "/api/v1/reports",
            headers=auth_headers,
            json={"period_start": "2030-01-01", "period_end": "2030-01-31"},
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["input_transaction_count"] == 0
        assert body["line_items"] == []
        assert body["status"] == "completed"

    def test_report_records_violations_for_invalid_currency(self, client, auth_headers):
        bad_currency_csv = (
            b"external_id,timestamp,amount,currency,counterparty,raw_category_hint\n"
            b"tx-bad-ccy,2026-02-01T10:00:00Z,10.00,US,Acme Corp,\n"
        )
        _upload(client, auth_headers, bad_currency_csv)

        response = client.post(
            "/api/v1/reports",
            headers=auth_headers,
            json={"period_start": "2026-02-01", "period_end": "2026-02-28"},
        )
        assert response.status_code == 201, response.text
        violations = response.json()["violations"]
        assert any(v["rule_id"] == "validate.currency_format" for v in violations)

    def test_report_records_violation_for_high_value_missing_counterparty(
        self, client, auth_headers
    ):
        # counterparty is syntactically optional at ingestion; whether it's
        # required depends on the amount, so this must pass ingestion and
        # only be caught by the rule engine at report-generation time.
        csv_content = (
            b"external_id,timestamp,amount,currency,counterparty,raw_category_hint\n"
            b"tx-no-counterparty,2026-03-01T10:00:00Z,25000.00,USD,,\n"
        )
        _upload(client, auth_headers, csv_content)

        response = client.post(
            "/api/v1/reports",
            headers=auth_headers,
            json={"period_start": "2026-03-01", "period_end": "2026-03-31"},
        )
        assert response.status_code == 201, response.text
        violations = response.json()["violations"]
        assert any(v["rule_id"] == "validate.high_value_requires_counterparty" for v in violations)
        # And it must still be classified/reported, not dropped.
        assert response.json()["input_transaction_count"] == 1

    def test_unknown_rule_set_version_is_rejected(self, client, auth_headers):
        response = client.post(
            "/api/v1/reports",
            headers=auth_headers,
            json={
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
                "rule_set_version": "v999-does-not-exist",
            },
        )
        assert response.status_code == 400

    def test_period_end_before_period_start_is_rejected(self, client, auth_headers):
        response = client.post(
            "/api/v1/reports",
            headers=auth_headers,
            json={"period_start": "2026-01-31", "period_end": "2026-01-01"},
        )
        assert response.status_code == 422


class TestListAndGetReport:
    def test_generated_report_appears_in_list_and_detail(self, client, auth_headers):
        _upload(client, auth_headers)
        trigger = client.post(
            "/api/v1/reports",
            headers=auth_headers,
            json={"period_start": "2026-01-01", "period_end": "2026-01-31"},
        )
        report_id = trigger.json()["id"]

        list_response = client.get("/api/v1/reports", headers=auth_headers)
        assert any(r["id"] == report_id for r in list_response.json())

        detail_response = client.get(f"/api/v1/reports/{report_id}", headers=auth_headers)
        assert detail_response.status_code == 200
        assert detail_response.json()["id"] == report_id

    def test_unknown_report_id_returns_404(self, client, auth_headers):
        response = client.get("/api/v1/reports/does-not-exist", headers=auth_headers)
        assert response.status_code == 404


class TestExportReport:
    def test_json_export_is_downloadable_and_matches_line_items(self, client, auth_headers):
        _upload(client, auth_headers)
        trigger = client.post(
            "/api/v1/reports",
            headers=auth_headers,
            json={"period_start": "2026-01-01", "period_end": "2026-01-31"},
        )
        report_id = trigger.json()["id"]

        response = client.get(
            f"/api/v1/reports/{report_id}/export?format=json", headers=auth_headers
        )
        assert response.status_code == 200
        exported = json.loads(response.content)
        assert exported["rule_set_version"] == "v1"
        assert len(exported["line_items"]) == len(trigger.json()["line_items"])

    def test_csv_export_is_downloadable(self, client, auth_headers):
        _upload(client, auth_headers)
        trigger = client.post(
            "/api/v1/reports",
            headers=auth_headers,
            json={"period_start": "2026-01-01", "period_end": "2026-01-31"},
        )
        report_id = trigger.json()["id"]

        response = client.get(
            f"/api/v1/reports/{report_id}/export?format=csv", headers=auth_headers
        )
        assert response.status_code == 200
        assert response.text.startswith("category,currency,metric_name")

    def test_pdf_export_is_downloadable(self, client, auth_headers):
        _upload(client, auth_headers)
        trigger = client.post(
            "/api/v1/reports",
            headers=auth_headers,
            json={"period_start": "2026-01-01", "period_end": "2026-01-31"},
        )
        report_id = trigger.json()["id"]

        response = client.get(
            f"/api/v1/reports/{report_id}/export?format=pdf", headers=auth_headers
        )
        assert response.status_code == 200
        assert response.content[:4] == b"%PDF"
