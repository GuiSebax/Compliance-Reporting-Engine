"""Shared pytest fixtures for the integration test suite.

Each test gets a fresh, isolated in-memory SQLite database (via
``StaticPool`` so the single connection is shared across the request
handled by the TestClient and any direct ``db_session`` access in the
test itself) — no test can leak state into another, and no external
Postgres instance is required to run ``pytest`` locally or in CI.

Environment variables are set at import time, before ``app.main`` (and
therefore ``app.core.config.get_settings``) is ever imported, since
``get_settings`` is cached.
"""

from __future__ import annotations

import os
import tempfile

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-do-not-use-in-production")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault(
    "REPORTS_LOCAL_DIR", tempfile.mkdtemp(prefix="compliance_reporting_test_exports_")
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.infrastructure.db import models  # noqa: E402,F401 register tables on Base.metadata
from app.infrastructure.db.base import Base  # noqa: E402
from app.infrastructure.db.repositories.user_repository import UserRepository  # noqa: E402
from app.infrastructure.db.session import get_db  # noqa: E402
from app.infrastructure.security.passwords import hash_password  # noqa: E402
from app.main import app  # noqa: E402

TEST_USER_EMAIL = "tester@example.com"
TEST_USER_PASSWORD = "Str0ngPassw0rd!1"


@pytest.fixture()
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture()
def _session_factory(db_engine):
    return sessionmaker(bind=db_engine, autoflush=False, autocommit=False, expire_on_commit=False)


@pytest.fixture()
def db_session(_session_factory):
    session = _session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(_session_factory):
    def _override_get_db():
        session = _session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def test_user(db_session):
    repo = UserRepository(db_session)
    user = repo.create(email=TEST_USER_EMAIL, hashed_password=hash_password(TEST_USER_PASSWORD))
    db_session.commit()
    return user


@pytest.fixture()
def auth_headers(client, test_user):
    response = client.post(
        "/api/v1/auth/login",
        data={"username": test_user.email, "password": TEST_USER_PASSWORD},
    )
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
