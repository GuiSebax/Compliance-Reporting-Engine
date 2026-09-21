"""End-to-end (API -> ingestion -> MongoDB double) tests for the rejection trail."""

from __future__ import annotations

import json

from app.application.rejection_store import RejectionStoreUnavailableError
from app.infrastructure.mongo.client import get_rejection_store
from app.main import app

CSV_WITH_BAD_ROWS = (
    b"external_id,timestamp,amount,currency,counterparty,raw_category_hint\n"
    b"tx-good,2026-01-05T10:00:00Z,150.00,USD,Acme Corp,\n"
    b"tx-bad,2026-01-06T11:00:00Z,not-a-number,USD,Globex Inc,\n"
    # Extra trailing cell -> csv.DictReader stores it under the None key.
    b"tx-wide,2026-01-07T11:00:00Z,oops,USD,Initech,,surprise\n"
)


def _upload(client, headers, name, content, content_type):
    response = client.post(
        "/api/v1/batches/upload",
        headers=headers,
        files={"file": (name, content, content_type)},
    )
    assert response.status_code == 201, response.text
    return response.json()


class TestRejectionsRecordedOnUpload:
    def test_rejected_csv_rows_land_in_mongo_with_raw_payload(
        self, client, auth_headers, rejection_store, mongo_collection
    ):
        batch = _upload(client, auth_headers, "q1.csv", CSV_WITH_BAD_ROWS, "text/csv")
        assert batch["rejected_row_count"] == 2

        docs = list(mongo_collection.find({"batch_id": batch["id"]}).sort("row_index", 1))
        assert [d["row_index"] for d in docs] == [1, 2]
        assert docs[0]["raw_payload"]["amount"] == "not-a-number"
        assert docs[0]["source_filename"] == "q1.csv"
        assert docs[0]["source_format"] == "csv"
        assert docs[0]["file_checksum_sha256"] == batch["checksum_sha256"]
        assert docs[0]["errors"][0]["loc"] == "amount"
        # The CSV "extra column" edge case survived BSON encoding.
        assert docs[1]["raw_payload"]["None"] == ["surprise"]

    def test_json_rows_keep_their_arbitrary_shape_and_exact_decimals(
        self, client, auth_headers, rejection_store, mongo_collection
    ):
        payload = {
            "transactions": [
                {"weird": {"nested": [1, 2]}, "amount": 1999.99},  # required fields missing
                "a bare string, not an object",
            ]
        }
        batch = _upload(
            client, auth_headers, "x.json", json.dumps(payload).encode(), "application/json"
        )
        assert batch["rejected_row_count"] == 2
        docs = list(mongo_collection.find({"batch_id": batch["id"]}).sort("row_index", 1))
        assert docs[0]["raw_payload"] == {"weird": {"nested": [1, 2]}, "amount": "1999.99"}
        assert docs[1]["raw_payload"] == "a bare string, not an object"
        assert docs[1]["errors"][0]["type"] == "value_error"

    def test_fully_valid_batch_writes_nothing(
        self, client, auth_headers, rejection_store, mongo_collection
    ):
        content = (
            b"external_id,timestamp,amount,currency,counterparty,raw_category_hint\n"
            b"tx-1,2026-01-05T10:00:00Z,150.00,USD,Acme Corp,\n"
        )
        _upload(client, auth_headers, "ok.csv", content, "text/csv")
        assert mongo_collection.count_documents({}) == 0

    def test_postgres_summary_is_unchanged_by_the_trail(
        self, client, auth_headers, rejection_store
    ):
        batch = _upload(client, auth_headers, "q1.csv", CSV_WITH_BAD_ROWS, "text/csv")
        detail = client.get(f"/api/v1/batches/{batch['id']}", headers=auth_headers).json()
        assert [r["row_index"] for r in detail["rejected_rows"]] == [1, 2]
        assert "raw_payload" not in detail["rejected_rows"][0]

    def test_mongo_outage_does_not_fail_the_upload(self, client, auth_headers):
        class DownStore:
            def record(self, context, rejections):
                raise RejectionStoreUnavailableError("mongo is down")

        app.dependency_overrides[get_rejection_store] = lambda: DownStore()
        batch = _upload(client, auth_headers, "q1.csv", CSV_WITH_BAD_ROWS, "text/csv")
        assert batch["accepted_row_count"] == 1
        assert batch["rejected_row_count"] == 2

    def test_upload_works_when_mongo_is_not_configured(self, client, auth_headers):
        # No override: MONGO_URL is unset in tests, so the null store is used.
        batch = _upload(client, auth_headers, "q1.csv", CSV_WITH_BAD_ROWS, "text/csv")
        assert batch["rejected_row_count"] == 2


class TestListRejectionsEndpoint:
    def test_returns_paginated_forensic_detail(self, client, auth_headers, rejection_store):
        batch = _upload(client, auth_headers, "q1.csv", CSV_WITH_BAD_ROWS, "text/csv")

        response = client.get(f"/api/v1/batches/{batch['id']}/rejections", headers=auth_headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 2
        assert [i["row_index"] for i in body["items"]] == [1, 2]
        assert body["items"][0]["raw_payload"]["external_id"] == "tx-bad"
        assert body["items"][0]["errors"][0]["loc"] == "amount"

        page = client.get(
            f"/api/v1/batches/{batch['id']}/rejections?limit=1&offset=1", headers=auth_headers
        ).json()
        assert page["total"] == 2
        assert [i["row_index"] for i in page["items"]] == [2]

    def test_unknown_batch_is_404(self, client, auth_headers, rejection_store):
        response = client.get("/api/v1/batches/nope/rejections", headers=auth_headers)
        assert response.status_code == 404

    def test_requires_authentication(self, client, rejection_store):
        assert client.get("/api/v1/batches/x/rejections").status_code == 401

    def test_invalid_pagination_is_rejected(self, client, auth_headers, rejection_store):
        batch = _upload(client, auth_headers, "q1.csv", CSV_WITH_BAD_ROWS, "text/csv")
        url = f"/api/v1/batches/{batch['id']}/rejections"
        assert client.get(url + "?limit=0", headers=auth_headers).status_code == 422
        assert client.get(url + "?limit=501", headers=auth_headers).status_code == 422
        assert client.get(url + "?offset=-1", headers=auth_headers).status_code == 422

    def test_503_when_mongo_not_configured(self, client, auth_headers):
        batch = _upload(client, auth_headers, "q1.csv", CSV_WITH_BAD_ROWS, "text/csv")
        response = client.get(f"/api/v1/batches/{batch['id']}/rejections", headers=auth_headers)
        assert response.status_code == 503
