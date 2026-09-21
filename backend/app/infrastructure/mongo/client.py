"""MongoDB client wiring.

``MongoClient`` connects lazily, so building it never fails or blocks —
an unreachable server only surfaces on the first operation, where
``MongoRejectionStore`` turns it into ``RejectionStoreUnavailableError``.
"""

from __future__ import annotations

from functools import lru_cache

from pymongo import MongoClient

from app.application.rejection_store import NullRejectionStore, RejectionStore
from app.core.config import get_settings
from app.infrastructure.logging import get_logger
from app.infrastructure.mongo.rejection_store import COLLECTION_NAME, MongoRejectionStore

logger = get_logger(__name__)


@lru_cache
def _client(url: str, timeout_ms: int) -> MongoClient:
    # tz_aware: datetimes read back are UTC-aware, matching what we write.
    return MongoClient(url, serverSelectionTimeoutMS=timeout_ms, tz_aware=True)


def get_rejection_store() -> RejectionStore:
    """The configured store, or a no-op one when ``MONGO_URL`` is unset."""
    settings = get_settings()
    if not settings.mongo_url:
        return NullRejectionStore()
    collection = _client(settings.mongo_url, settings.mongo_server_selection_timeout_ms)[
        settings.mongo_db_name
    ][COLLECTION_NAME]
    return MongoRejectionStore(collection, ttl_days=settings.mongo_rejection_ttl_days)


def ensure_mongo_indexes() -> None:
    """Startup hook: create indexes if Mongo is configured; never raises."""
    store = get_rejection_store()
    if not isinstance(store, MongoRejectionStore):
        return
    try:
        store.ensure_indexes()
        logger.info("mongo_indexes_ensured", collection=COLLECTION_NAME)
    except Exception as exc:  # noqa: BLE001 - startup must not depend on Mongo being up
        logger.warning("mongo_index_setup_failed", error=str(exc))
