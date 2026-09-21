"""Unit tests for the MongoDB rejection store (mongomock — no server needed)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import bson
import mongomock
import pytest
from pymongo.errors import PyMongoError

from app.application.rejection_store import (
    NullRejectionStore,
    RejectionContext,
    RejectionDetail,
    RejectionStoreUnavailableError,
    record_rejections_best_effort,
)
from app.infrastructure.mongo.rejection_store import MongoRejectionStore, sanitize_for_bson

CONTEXT = RejectionContext(
    batch_id="batch-1",
    source_filename="q1.csv",
    source_format="csv",
    file_checksum_sha256="a" * 64,
)


def _detail(index: int, payload: object = None) -> RejectionDetail:
    return RejectionDetail(
        row_index=index,
        reason=f"row {index} invalid",
        raw_payload={"external_id": f"tx-{index}"} if payload is None else payload,
        errors=({"loc": "amount", "type": "decimal_parsing", "msg": "bad amount"},),
    )


@pytest.fixture()
def collection():
    return mongomock.MongoClient(tz_aware=True)["t"]["ingestion_rejections"]


@pytest.fixture()
def store(collection):
    s = MongoRejectionStore(collection, ttl_days=30)
    s.ensure_indexes()
    return s


class TestSanitizeForBson:
    def test_decimal_becomes_exact_string_not_float(self):
        assert sanitize_for_bson(Decimal("1999.99")) == "1999.99"

    def test_none_key_from_csv_extra_columns_is_stringified(self):
        # csv.DictReader puts cells beyond the header under the key None.
        row = {"external_id": "tx-1", None: ["extra1", "extra2"]}
        cleaned = sanitize_for_bson(row)
        assert cleaned == {"external_id": "tx-1", "None": ["extra1", "extra2"]}

    def test_nested_structures_are_cleaned_recursively(self):
        cleaned = sanitize_for_bson({"a": {"b": [Decimal("1.5"), {"c": (1, 2)}]}})
        assert cleaned == {"a": {"b": ["1.5", {"c": [1, 2]}]}}

    def test_oversized_integer_is_stringified(self):
        assert sanitize_for_bson(2**70) == str(2**70)
        assert sanitize_for_bson(2**63 - 1) == 2**63 - 1

    def test_nul_in_key_is_escaped(self):
        assert sanitize_for_bson({"a\x00b": 1}) == {"a\\0b": 1}

    def test_unknown_objects_fall_back_to_str(self):
        assert sanitize_for_bson(object) == str(object)

    def test_result_is_actually_encodable_as_bson(self):
        messy = {
            "amount": Decimal("10.10"),
            None: ["x"],
            "big": 2**70,
            "when": datetime(2026, 1, 1, tzinfo=UTC),
            "nested": {"tags": {"a"}},
        }
        bson.encode(sanitize_for_bson(messy))  # would raise on failure


class TestMongoRejectionStore:
    def test_record_persists_documents_with_context_and_ttl_field(self, store, collection):
        stored = store.record(CONTEXT, [_detail(0), _detail(3)])
        assert stored == 2
        doc = collection.find_one({"row_index": 3})
        assert doc["batch_id"] == "batch-1"
        assert doc["source_filename"] == "q1.csv"
        assert doc["source_format"] == "csv"
        assert doc["file_checksum_sha256"] == "a" * 64
        assert doc["raw_payload"] == {"external_id": "tx-3"}
        assert doc["errors"][0]["loc"] == "amount"
        assert isinstance(doc["rejected_at"], datetime)

    def test_documents_may_have_different_shapes(self, store):
        """The reason this is MongoDB: payload shape is the uploader's."""
        store.record(
            CONTEXT,
            [
                _detail(0, {"external_id": "a", "amount": "x"}),
                _detail(1, {"id": 7, "nested": {"deep": [1, 2, 3]}, "note": None}),
                _detail(2, ["not", "an", "object"]),
            ],
        )
        payloads = [r.raw_payload for r in store.list_for_batch("batch-1")]
        assert payloads[1] == {"id": 7, "nested": {"deep": [1, 2, 3]}, "note": None}
        assert payloads[2] == ["not", "an", "object"]

    def test_list_is_scoped_to_batch_sorted_and_paginated(self, store):
        store.record(CONTEXT, [_detail(i) for i in (5, 1, 3)])
        other = RejectionContext("batch-2", "o.json", "json", "b" * 64)
        store.record(other, [_detail(0)])

        rows = store.list_for_batch("batch-1")
        assert [r.row_index for r in rows] == [1, 3, 5]
        assert [r.row_index for r in store.list_for_batch("batch-1", limit=1, offset=1)] == [3]
        assert store.count_for_batch("batch-1") == 3
        assert store.count_for_batch("batch-2") == 1
        assert store.count_for_batch("missing") == 0

    def test_list_returns_typed_details(self, store):
        store.record(CONTEXT, [_detail(2)])
        (row,) = store.list_for_batch("batch-1")
        assert row.id
        assert row.errors[0].msg == "bad amount"
        assert row.rejected_at.tzinfo is not None

    def test_record_with_no_rejections_is_a_noop(self, store, collection):
        assert store.record(CONTEXT, []) == 0
        assert collection.count_documents({}) == 0

    def test_ensure_indexes_creates_ttl_with_configured_retention(self, store, collection):
        info = collection.index_information()
        assert info["ttl_rejected_at"]["expireAfterSeconds"] == 30 * 24 * 60 * 60
        assert [k for k, _ in info["ix_batch_row"]["key"]] == ["batch_id", "row_index"]

    def test_ensure_indexes_is_idempotent(self, store):
        store.ensure_indexes()
        store.ensure_indexes()

    def test_ttl_days_must_be_positive(self, collection):
        with pytest.raises(ValueError):
            MongoRejectionStore(collection, ttl_days=0)

    def test_driver_errors_become_unavailable_error(self):
        class Broken:
            def insert_many(self, *a, **k):
                raise PyMongoError("connection refused")

            def find(self, *a, **k):
                raise PyMongoError("connection refused")

            def count_documents(self, *a, **k):
                raise PyMongoError("connection refused")

        broken = MongoRejectionStore(Broken(), ttl_days=1)  # type: ignore[arg-type]
        with pytest.raises(RejectionStoreUnavailableError):
            broken.record(CONTEXT, [_detail(0)])
        with pytest.raises(RejectionStoreUnavailableError):
            broken.list_for_batch("batch-1")
        with pytest.raises(RejectionStoreUnavailableError):
            broken.count_for_batch("batch-1")


class TestBestEffortRecording:
    def test_failure_is_swallowed_and_reports_zero(self):
        class Exploding:
            def record(self, context, rejections):
                raise RejectionStoreUnavailableError("down")

        assert record_rejections_best_effort(Exploding(), CONTEXT, [_detail(0)]) == 0  # type: ignore[arg-type]

    def test_unexpected_exception_is_also_swallowed(self):
        class Exploding:
            def record(self, context, rejections):
                raise RuntimeError("boom")

        assert record_rejections_best_effort(Exploding(), CONTEXT, [_detail(0)]) == 0  # type: ignore[arg-type]

    def test_success_returns_stored_count(self, store):
        assert record_rejections_best_effort(store, CONTEXT, [_detail(0), _detail(1)]) == 2

    def test_nothing_to_record_does_not_touch_the_store(self):
        class MustNotBeCalled:
            def record(self, context, rejections):
                raise AssertionError("should not be called")

        assert record_rejections_best_effort(MustNotBeCalled(), CONTEXT, []) == 0  # type: ignore[arg-type]


class TestNullStore:
    def test_record_is_a_noop(self):
        assert NullRejectionStore().record(CONTEXT, [_detail(0)]) == 0

    def test_reads_report_unavailable_instead_of_empty(self):
        with pytest.raises(RejectionStoreUnavailableError):
            NullRejectionStore().list_for_batch("x")
        with pytest.raises(RejectionStoreUnavailableError):
            NullRejectionStore().count_for_batch("x")
