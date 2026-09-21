"""Tests for the Lambda/EventBridge provisioning script (fake AWS clients)."""

from __future__ import annotations

import hashlib

import pytest
from botocore.exceptions import ClientError

from scripts.provision_lambda import (
    DEFAULT_SCHEDULE,
    ProvisionConfig,
    parse_env_pairs,
    provision,
)

FUNCTION_ARN = "arn:aws:lambda:us-east-1:000000000000:function:compliance-scheduled-report"
RULE_ARN = "arn:aws:events:us-east-1:000000000000:rule/compliance-monthly-report"


def _client_error(code: str, operation: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, operation)


class _Waiter:
    def wait(self, **kwargs):
        pass


class FakeLambda:
    def __init__(self, *, exists: bool, permission_conflict: bool = False):
        self.exists = exists
        self.permission_conflict = permission_conflict
        self.calls: list[tuple[str, dict]] = []

    def get_function(self, **kwargs):
        if not self.exists:
            raise _client_error("ResourceNotFoundException", "GetFunction")
        return {"Configuration": {"FunctionArn": FUNCTION_ARN}}

    def create_function(self, **kwargs):
        self.calls.append(("create_function", kwargs))
        self.exists = True

    def update_function_code(self, **kwargs):
        self.calls.append(("update_function_code", kwargs))

    def update_function_configuration(self, **kwargs):
        self.calls.append(("update_function_configuration", kwargs))

    def add_permission(self, **kwargs):
        self.calls.append(("add_permission", kwargs))
        if self.permission_conflict:
            raise _client_error("ResourceConflictException", "AddPermission")

    def get_waiter(self, name):
        return _Waiter()

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]

    def args(self, name: str) -> dict:
        return next(kwargs for n, kwargs in self.calls if n == name)


class FakeEvents:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def put_rule(self, **kwargs):
        self.calls.append(("put_rule", kwargs))
        return {"RuleArn": RULE_ARN}

    def put_targets(self, **kwargs):
        self.calls.append(("put_targets", kwargs))


class FakeS3:
    def __init__(self, *, buckets: set[str] | None = None, objects: set[str] | None = None):
        self.buckets = buckets if buckets is not None else set()
        self.objects = objects if objects is not None else set()
        self.created: list[str] = []
        self.puts: list[dict] = []

    def head_bucket(self, Bucket):
        if Bucket not in self.buckets:
            raise _client_error("404", "HeadBucket")

    def create_bucket(self, Bucket):
        self.buckets.add(Bucket)
        self.created.append(Bucket)

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise _client_error("404", "HeadObject")

    def put_object(self, Bucket, Key, Body):
        self.objects.add(Key)
        self.puts.append({"Bucket": Bucket, "Key": Key, "Body": Body})


ZIP_BYTES = b"PK-fake-zip-content"
ZIP_KEY = f"lambda/compliance-scheduled-report/{hashlib.sha256(ZIP_BYTES).hexdigest()[:16]}.zip"


@pytest.fixture()
def config(tmp_path) -> ProvisionConfig:
    zip_path = tmp_path / "report-lambda.zip"
    zip_path.write_bytes(ZIP_BYTES)
    return ProvisionConfig(
        function_name="compliance-scheduled-report",
        zip_path=str(zip_path),
        artifact_bucket="artifacts",
        role_arn="arn:aws:iam::000000000000:role/compliance-report-lambda",
        rule_name="compliance-monthly-report",
        schedule_expression=DEFAULT_SCHEDULE,
        environment={"DATABASE_URL": "postgresql+psycopg://x", "S3_BUCKET_NAME": "b"},
    )


def _run(config, *, lam=None, events=None, s3=None):
    lam = lam or FakeLambda(exists=False)
    events = events or FakeEvents()
    s3 = s3 or FakeS3(buckets={"artifacts"})
    result = provision(lambda_client=lam, events_client=events, s3_client=s3, config=config)
    return result, lam, events, s3


class TestProvision:
    def test_first_run_creates_function_rule_permission_and_target(self, config):
        result, lam, events, _ = _run(config)

        assert lam.names() == ["create_function", "add_permission"]
        created = lam.args("create_function")
        assert created["PackageType"] == "Zip"
        assert created["Runtime"] == "python3.12"
        assert created["Handler"] == "app.lambda_handlers.scheduled_report.handler"
        assert created["Code"] == {"S3Bucket": "artifacts", "S3Key": ZIP_KEY}
        assert created["Environment"] == {"Variables": config.environment}
        assert result == {
            "function_arn": FUNCTION_ARN,
            "rule_arn": RULE_ARN,
            "schedule": "cron(0 3 1 * ? *)",
            "artifact": f"s3://artifacts/{ZIP_KEY}",
        }

    def test_rerun_updates_instead_of_creating(self, config):
        _, lam, _, _ = _run(config, lam=FakeLambda(exists=True))

        assert "create_function" not in lam.names()
        assert lam.args("update_function_code") == {
            "FunctionName": "compliance-scheduled-report",
            "S3Bucket": "artifacts",
            "S3Key": ZIP_KEY,
        }
        assert lam.args("update_function_configuration")["Role"] == config.role_arn

    def test_schedule_and_target_are_wired_to_the_function(self, config):
        _, _, events, _ = _run(config)

        rule = dict(events.calls)["put_rule"]
        assert rule["ScheduleExpression"] == "cron(0 3 1 * ? *)"
        assert rule["State"] == "ENABLED"
        target = dict(events.calls)["put_targets"]
        assert target["Rule"] == "compliance-monthly-report"
        assert target["Targets"][0]["Arn"] == FUNCTION_ARN

    def test_invoke_permission_is_scoped_to_the_rule(self, config):
        _, lam, _, _ = _run(config)

        permission = lam.args("add_permission")
        assert permission["Principal"] == "events.amazonaws.com"
        assert permission["SourceArn"] == RULE_ARN  # not any rule in the account
        assert permission["Action"] == "lambda:InvokeFunction"

    def test_existing_permission_is_not_an_error(self, config):
        _, _, events, _ = _run(config, lam=FakeLambda(exists=True, permission_conflict=True))

        assert "put_targets" in dict(events.calls)  # continued past the conflict

    def test_other_permission_errors_propagate(self, config):
        class Denied(FakeLambda):
            def add_permission(self, **kwargs):
                raise _client_error("AccessDeniedException", "AddPermission")

        with pytest.raises(ClientError):
            _run(config, lam=Denied(exists=True))


class TestPackageUpload:
    def test_package_is_uploaded_under_a_content_hashed_key(self, config):
        _, _, _, s3 = _run(config)

        assert s3.puts == [{"Bucket": "artifacts", "Key": ZIP_KEY, "Body": ZIP_BYTES}]

    def test_unchanged_package_is_not_uploaded_again(self, config):
        s3 = FakeS3(buckets={"artifacts"}, objects={ZIP_KEY})

        _run(config, s3=s3)

        assert s3.puts == []

    def test_unexpected_s3_errors_propagate(self, config):
        class Denied(FakeS3):
            def head_object(self, Bucket, Key):
                raise _client_error("AccessDenied", "HeadObject")

        with pytest.raises(ClientError):
            _run(config, s3=Denied(buckets={"artifacts"}))


class TestEnsureBucket:
    def test_creates_missing_buckets_before_uploading(self, config):
        s3 = FakeS3()
        cfg = ProvisionConfig(**{**config.__dict__, "ensure_buckets": ("artifacts", "reports")})

        _run(cfg, s3=s3)

        assert s3.created == ["artifacts", "reports"]
        assert s3.puts  # upload succeeded because the bucket now exists

    def test_leaves_existing_bucket_alone(self, config):
        s3 = FakeS3(buckets={"artifacts"})
        cfg = ProvisionConfig(**{**config.__dict__, "ensure_buckets": ("artifacts",)})

        _run(cfg, s3=s3)

        assert s3.created == []


class TestParseEnvPairs:
    def test_splits_on_first_equals_only(self):
        # DATABASE_URL-style values legitimately contain '='.
        assert parse_env_pairs(["A=1", "URL=postgresql://h/db?x=y"]) == {
            "A": "1",
            "URL": "postgresql://h/db?x=y",
        }

    def test_empty_value_is_allowed(self):
        assert parse_env_pairs(["EMPTY="]) == {"EMPTY": ""}

    @pytest.mark.parametrize("bad", ["NOEQUALS", "=novalue", ""])
    def test_malformed_pairs_are_rejected(self, bad):
        with pytest.raises(ValueError):
            parse_env_pairs([bad])
