"""Wiring of the Mongo store: configuration switch and startup resilience."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.application.rejection_store import NullRejectionStore
from app.infrastructure.mongo import client
from app.infrastructure.mongo.rejection_store import MongoRejectionStore


def _settings(**overrides):
    base = {
        "mongo_url": None,
        "mongo_db_name": "compliance",
        "mongo_server_selection_timeout_ms": 100,
        "mongo_rejection_ttl_days": 90,
    }
    return SimpleNamespace(**{**base, **overrides})


@pytest.fixture(autouse=True)
def _clear_client_cache():
    client._client.cache_clear()
    yield
    client._client.cache_clear()


def test_unset_url_yields_the_null_store(monkeypatch):
    monkeypatch.setattr(client, "get_settings", lambda: _settings())
    assert isinstance(client.get_rejection_store(), NullRejectionStore)


def test_configured_url_yields_the_mongo_store(monkeypatch):
    monkeypatch.setattr(
        client, "get_settings", lambda: _settings(mongo_url="mongodb://localhost:1")
    )
    assert isinstance(client.get_rejection_store(), MongoRejectionStore)


def test_client_is_created_once_per_configuration(monkeypatch):
    monkeypatch.setattr(
        client, "get_settings", lambda: _settings(mongo_url="mongodb://localhost:1")
    )
    client.get_rejection_store()
    client.get_rejection_store()
    assert client._client.cache_info().misses == 1


def test_startup_index_setup_never_raises_when_mongo_is_unreachable(monkeypatch):
    # Port 1: nothing listens. The API must still boot (Mongo is best-effort).
    monkeypatch.setattr(
        client, "get_settings", lambda: _settings(mongo_url="mongodb://localhost:1")
    )
    client.ensure_mongo_indexes()  # would raise ServerSelectionTimeoutError if not guarded


def test_startup_index_setup_is_a_noop_without_mongo(monkeypatch):
    monkeypatch.setattr(client, "get_settings", lambda: _settings())
    client.ensure_mongo_indexes()
