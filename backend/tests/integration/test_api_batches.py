import json

CSV_CONTENT = (
    b"external_id,timestamp,amount,currency,counterparty,raw_category_hint\n"
    b"tx-1,2026-01-05T10:00:00Z,150.00,USD,Acme Corp,\n"
    b"tx-2,2026-01-06T11:00:00Z,15000.00,USD,Globex Inc,wire\n"
)

CSV_WITH_BAD_ROW = (
    b"external_id,timestamp,amount,currency,counterparty,raw_category_hint\n"
    b"tx-good,2026-01-05T10:00:00Z,150.00,USD,Acme Corp,\n"
    b"tx-bad,2026-01-06T11:00:00Z,not-a-number,USD,Globex Inc,\n"
)


class TestUploadCsv:
    def test_valid_csv_is_fully_accepted(self, client, auth_headers):
        response = client.post(
            "/api/v1/batches/upload",
            headers=auth_headers,
            files={"file": ("transactions.csv", CSV_CONTENT, "text/csv")},
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["row_count"] == 2
        assert body["accepted_row_count"] == 2
        assert body["rejected_row_count"] == 0
        assert len(body["checksum_sha256"]) == 64

    def test_partially_invalid_csv_reports_rejected_rows(self, client, auth_headers):
        response = client.post(
            "/api/v1/batches/upload",
            headers=auth_headers,
            files={"file": ("transactions.csv", CSV_WITH_BAD_ROW, "text/csv")},
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["accepted_row_count"] == 1
        assert body["rejected_row_count"] == 1
        assert body["rejected_rows"][0]["row_index"] == 1

    def test_empty_file_is_rejected(self, client, auth_headers):
        response = client.post(
            "/api/v1/batches/upload",
            headers=auth_headers,
            files={"file": ("empty.csv", b"", "text/csv")},
        )
        assert response.status_code == 400

    def test_unsupported_extension_is_rejected(self, client, auth_headers):
        response = client.post(
            "/api/v1/batches/upload",
            headers=auth_headers,
            files={"file": ("transactions.txt", b"hello", "text/plain")},
        )
        assert response.status_code in (400, 415)


class TestUploadJson:
    def test_valid_json_list_is_accepted(self, client, auth_headers):
        payload = [
            {
                "external_id": "tx-json-1",
                "timestamp": "2026-01-10T09:00:00Z",
                "amount": "42.50",
                "currency": "USD",
                "counterparty": "Acme Corp",
            }
        ]
        response = client.post(
            "/api/v1/batches/upload",
            headers=auth_headers,
            files={
                "file": (
                    "transactions.json",
                    json.dumps(payload).encode("utf-8"),
                    "application/json",
                )
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["accepted_row_count"] == 1

    def test_json_amount_preserves_decimal_precision(self, client, auth_headers):
        # 10.1 + 20.2 must equal exactly 30.3 downstream; that requires the
        # ingestion layer to never round-trip amounts through a Python float.
        payload = {
            "transactions": [
                {
                    "external_id": "tx-a",
                    "timestamp": "2026-01-10T09:00:00Z",
                    "amount": 10.10,
                    "currency": "USD",
                    "counterparty": "Acme",
                }
            ]
        }
        response = client.post(
            "/api/v1/batches/upload",
            headers=auth_headers,
            files={
                "file": (
                    "transactions.json",
                    json.dumps(payload).encode("utf-8"),
                    "application/json",
                )
            },
        )
        assert response.status_code == 201, response.text
        assert response.json()["accepted_row_count"] == 1

    def test_malformed_json_is_rejected(self, client, auth_headers):
        response = client.post(
            "/api/v1/batches/upload",
            headers=auth_headers,
            files={"file": ("bad.json", b"{not valid json", "application/json")},
        )
        assert response.status_code == 400


class TestListAndGetBatch:
    def test_uploaded_batch_appears_in_list_and_detail(self, client, auth_headers):
        upload = client.post(
            "/api/v1/batches/upload",
            headers=auth_headers,
            files={"file": ("transactions.csv", CSV_CONTENT, "text/csv")},
        )
        batch_id = upload.json()["id"]

        list_response = client.get("/api/v1/batches", headers=auth_headers)
        assert list_response.status_code == 200
        assert any(b["id"] == batch_id for b in list_response.json())

        detail_response = client.get(f"/api/v1/batches/{batch_id}", headers=auth_headers)
        assert detail_response.status_code == 200
        assert detail_response.json()["id"] == batch_id

    def test_unknown_batch_id_returns_404(self, client, auth_headers):
        response = client.get("/api/v1/batches/does-not-exist", headers=auth_headers)
        assert response.status_code == 404
