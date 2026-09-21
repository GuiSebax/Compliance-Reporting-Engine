"""Contract tests against a *real* MongoDB server.

mongomock is a faithful-enough double for query logic, but it does not
enforce BSON encoding rules or run the TTL monitor. These tests close that
gap. They are skipped unless ``MONGO_TEST_URL`` is set, e.g.::

    docker run -d -p 27018:27017 mongo:7
    MONGO_TEST_URL=mongodb://localhost:27018 pytest tests/integration/test_mongo_real.py

CI provides a ``mongo:7`` service container and sets the variable.
"""

from __future__ import annotations

import os
import uuid
from decimal import Decimal

import pytest
from pymongo import MongoClient

from app.application.rejection_store import RejectionContext, RejectionDetail
from app.infrastructure.mongo.rejection_store import COLLECTION_NAME, MongoRejectionStore

MONGO_TEST_URL = os.environ.get("MONGO_TEST_URL")

pytestmark = pytest.mark.skipif(not MONGO_TEST_URL, reason="MONGO_TEST_URL not set")


@pytest.fixture()
def real_store():
    client = MongoClient(MONGO_TEST_URL, serverSelectionTimeoutMS=3000, tz_aware=True)
    db_name = f"compliance_test_{uuid.uuid4().hex[:8]}"
    store = MongoRejectionStore(client[db_name][COLLECTION_NAME], ttl_days=7)
    store.ensure_indexes()
    yield store, client[db_name][COLLECTION_NAME]
    client.drop_database(db_name)
    client.close()


def test_messy_payloads_round_trip_through_a_real_server(real_store):
    store, _ = real_store
    context = RejectionContext("batch-real", "messy.csv", "csv", "c" * 64)
    messy = {
        "external_id": "tx-1",
        "amount": Decimal("1999.99"),  # bson.encode would reject a raw Decimal
        None: ["csv", "overflow"],  # csv.DictReader's key for extra cells
        "huge": 2**80,  # wider than BSON int64
        "$dollar": {"a.b": 1},  # operator-looking / dotted keys from untrusted input
    }
    detail = RejectionDetail(
        row_index=0,
        reason="bad",
        raw_payload=messy,
        errors=({"loc": "amount", "type": "decimal_parsing", "msg": "bad"},),
    )

    assert store.record(context, [detail]) == 1

    (row,) = store.list_for_batch("batch-real")
    assert row.raw_payload["amount"] == "1999.99"
    assert row.raw_payload["None"] == ["csv", "overflow"]
    assert row.raw_payload["huge"] == str(2**80)
    assert row.raw_payload["$dollar"] == {"a.b": 1}
    assert store.count_for_batch("batch-real") == 1


def test_ttl_and_lookup_indexes_exist_on_a_real_server(real_store):
    _, collection = real_store
    info = collection.index_information()
    assert info["ttl_rejected_at"]["expireAfterSeconds"] == 7 * 24 * 60 * 60
    assert info["ix_batch_row"]["key"] == [("batch_id", 1), ("row_index", 1)]
