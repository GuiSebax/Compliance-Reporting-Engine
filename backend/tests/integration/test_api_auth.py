from tests.conftest import TEST_USER_EMAIL, TEST_USER_PASSWORD


class TestRegister:
    def test_register_creates_a_user(self, client):
        response = client.post(
            "/api/v1/auth/register",
            json={"email": "new-user@example.com", "password": "SuperSecret1!"},
        )
        assert response.status_code == 201
        assert response.json()["email"] == "new-user@example.com"

    def test_register_rejects_duplicate_email(self, client, test_user):
        response = client.post(
            "/api/v1/auth/register",
            json={"email": test_user.email, "password": "AnotherPassword1!"},
        )
        assert response.status_code == 409

    def test_register_rejects_malformed_email(self, client):
        response = client.post(
            "/api/v1/auth/register",
            json={"email": "not-an-email", "password": "SuperSecret1!"},
        )
        assert response.status_code == 422

    def test_register_rejects_short_password(self, client):
        response = client.post(
            "/api/v1/auth/register",
            json={"email": "short-pw@example.com", "password": "short"},
        )
        assert response.status_code == 422


class TestLogin:
    def test_login_with_correct_credentials_returns_a_token(self, client, test_user):
        response = client.post(
            "/api/v1/auth/login",
            data={"username": TEST_USER_EMAIL, "password": TEST_USER_PASSWORD},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["token_type"] == "bearer"
        assert len(body["access_token"]) > 20

    def test_login_with_wrong_password_is_rejected(self, client, test_user):
        response = client.post(
            "/api/v1/auth/login",
            data={"username": TEST_USER_EMAIL, "password": "wrong-password"},
        )
        assert response.status_code == 401

    def test_login_with_unknown_email_is_rejected(self, client):
        response = client.post(
            "/api/v1/auth/login",
            data={"username": "ghost@example.com", "password": "whatever"},
        )
        assert response.status_code == 401


class TestProtectedEndpoints:
    def test_upload_without_token_is_rejected(self, client):
        response = client.post(
            "/api/v1/batches/upload",
            files={"file": ("data.csv", b"external_id\n", "text/csv")},
        )
        assert response.status_code == 401

    def test_trigger_report_without_token_is_rejected(self, client):
        response = client.post(
            "/api/v1/reports",
            json={"period_start": "2026-01-01", "period_end": "2026-01-31"},
        )
        assert response.status_code == 401

    def test_upload_with_invalid_token_is_rejected(self, client):
        response = client.post(
            "/api/v1/batches/upload",
            headers={"Authorization": "Bearer not-a-real-token"},
            files={"file": ("data.csv", b"external_id\n", "text/csv")},
        )
        assert response.status_code == 401
