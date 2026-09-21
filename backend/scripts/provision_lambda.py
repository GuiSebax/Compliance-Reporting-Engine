#!/usr/bin/env python
"""Provision the scheduled-report Lambda and its EventBridge schedule.

Idempotent: safe to re-run (creates on first run, updates afterwards).
Works against LocalStack *and* real AWS — the only difference is the
endpoint. boto3 honours ``AWS_ENDPOINT_URL`` natively, so::

    # LocalStack (role ARN is not validated there)
    AWS_ENDPOINT_URL=http://localhost:4566 AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test \\
      python scripts/provision_lambda.py \\
        --zip-path dist/report-lambda.zip \\
        --artifact-bucket lambda-artifacts --ensure-bucket lambda-artifacts \\
        --role-arn arn:aws:iam::000000000000:role/compliance-report-lambda \\
        --env DATABASE_URL=postgresql+psycopg://... --env S3_BUCKET_NAME=compliance-reports

    # Real AWS: no endpoint override; the IAM role and the artifact bucket
    # must already exist (see README "Going to real AWS").

The package is always uploaded to S3 and referenced from there: a direct
``ZipFile`` upload is capped at 50 MB, and this package is larger.

What it sets up:
  1. the Lambda function (zip package, python3.12) with its environment;
  2. an EventBridge rule with a schedule expression;
  3. permission for EventBridge to invoke the function (scoped to that rule);
  4. the rule -> function target.

It deliberately does *not* create the IAM role: role creation needs broader
permissions than a deploy step should have, and belongs in your IaC.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import dataclass, field
from typing import Any

import boto3
from botocore.exceptions import ClientError

# Monthly: 03:00 UTC on the 1st. The handler reports the month that just ended.
DEFAULT_SCHEDULE = "cron(0 3 1 * ? *)"
DEFAULT_HANDLER = "app.lambda_handlers.scheduled_report.handler"


@dataclass(frozen=True)
class ProvisionConfig:
    function_name: str
    zip_path: str
    artifact_bucket: str
    role_arn: str
    rule_name: str
    schedule_expression: str
    environment: dict[str, str] = field(default_factory=dict)
    runtime: str = "python3.12"
    handler: str = DEFAULT_HANDLER
    timeout_seconds: int = 300
    memory_mb: int = 1024
    ensure_buckets: tuple[str, ...] = ()


def parse_env_pairs(pairs: list[str]) -> dict[str, str]:
    """``["A=1", "B=x=y"]`` -> ``{"A": "1", "B": "x=y"}`` (split on first ``=``)."""
    env: dict[str, str] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise ValueError(f"Invalid --env '{pair}': expected KEY=VALUE")
        env[key] = value
    return env


def _error_code(exc: ClientError) -> str:
    return exc.response.get("Error", {}).get("Code", "")


def _function_exists(lambda_client: Any, name: str) -> bool:
    try:
        lambda_client.get_function(FunctionName=name)
        return True
    except ClientError as exc:
        if _error_code(exc) == "ResourceNotFoundException":
            return False
        raise


def _wait_until_updatable(lambda_client: Any, name: str) -> None:
    lambda_client.get_waiter("function_active_v2").wait(FunctionName=name)
    lambda_client.get_waiter("function_updated_v2").wait(FunctionName=name)


def upload_package(s3_client: Any, config: ProvisionConfig) -> str:
    """Upload the zip to the artifact bucket; returns its key.

    The key embeds a content hash, so an unchanged package is not
    re-uploaded and every distinct build keeps its own object (handy for
    rollbacks: point the function at an older key).
    """
    with open(config.zip_path, "rb") as fh:
        content = fh.read()
    key = f"lambda/{config.function_name}/{hashlib.sha256(content).hexdigest()[:16]}.zip"
    try:
        s3_client.head_object(Bucket=config.artifact_bucket, Key=key)
    except ClientError as exc:
        if _error_code(exc) not in ("404", "NoSuchKey", "NotFound"):
            raise
        s3_client.put_object(Bucket=config.artifact_bucket, Key=key, Body=content)
    return key


def upsert_function(lambda_client: Any, config: ProvisionConfig, artifact_key: str) -> str:
    """Create or update the function; returns its ARN."""
    code = {"S3Bucket": config.artifact_bucket, "S3Key": artifact_key}
    settings = {
        "Role": config.role_arn,
        "Runtime": config.runtime,
        "Handler": config.handler,
        "Timeout": config.timeout_seconds,
        "MemorySize": config.memory_mb,
        "Environment": {"Variables": config.environment},
    }
    if _function_exists(lambda_client, config.function_name):
        lambda_client.update_function_code(FunctionName=config.function_name, **code)
        _wait_until_updatable(lambda_client, config.function_name)
        lambda_client.update_function_configuration(FunctionName=config.function_name, **settings)
    else:
        lambda_client.create_function(
            FunctionName=config.function_name, PackageType="Zip", Code=code, **settings
        )
    _wait_until_updatable(lambda_client, config.function_name)
    return lambda_client.get_function(FunctionName=config.function_name)["Configuration"][
        "FunctionArn"
    ]


def upsert_schedule(events_client: Any, lambda_client: Any, config: ProvisionConfig, arn: str):
    """Create/update the rule, allow it to invoke the function, attach the target."""
    rule_arn = events_client.put_rule(
        Name=config.rule_name,
        ScheduleExpression=config.schedule_expression,
        State="ENABLED",
        Description="Monthly compliance report generation",
    )["RuleArn"]

    try:
        lambda_client.add_permission(
            FunctionName=config.function_name,
            StatementId=f"{config.rule_name}-invoke",
            Action="lambda:InvokeFunction",
            Principal="events.amazonaws.com",
            SourceArn=rule_arn,  # only *this* rule may invoke the function
        )
    except ClientError as exc:
        if _error_code(exc) != "ResourceConflictException":  # already granted
            raise

    events_client.put_targets(
        Rule=config.rule_name, Targets=[{"Id": "scheduled-report-lambda", "Arn": arn}]
    )
    return rule_arn


def ensure_bucket(s3_client: Any, bucket: str) -> None:
    try:
        s3_client.head_bucket(Bucket=bucket)
    except ClientError:
        s3_client.create_bucket(Bucket=bucket)


def provision(
    *, lambda_client: Any, events_client: Any, s3_client: Any, config: ProvisionConfig
) -> dict[str, str]:
    for bucket in config.ensure_buckets:
        ensure_bucket(s3_client, bucket)
    artifact_key = upload_package(s3_client, config)
    arn = upsert_function(lambda_client, config, artifact_key)
    rule_arn = upsert_schedule(events_client, lambda_client, config, arn)
    return {
        "function_arn": arn,
        "rule_arn": rule_arn,
        "schedule": config.schedule_expression,
        "artifact": f"s3://{config.artifact_bucket}/{artifact_key}",
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--function-name", default="compliance-scheduled-report")
    parser.add_argument("--zip-path", required=True, help="Deployment package (.zip)")
    parser.add_argument(
        "--artifact-bucket", required=True, help="S3 bucket the package is uploaded to"
    )
    parser.add_argument("--runtime", default="python3.12")
    parser.add_argument("--handler", default=DEFAULT_HANDLER)
    parser.add_argument("--role-arn", required=True, help="Lambda execution role ARN")
    parser.add_argument("--rule-name", default="compliance-monthly-report")
    parser.add_argument("--schedule-expression", default=DEFAULT_SCHEDULE)
    parser.add_argument("--env", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--memory", type=int, default=1024)
    parser.add_argument(
        "--ensure-bucket",
        action="append",
        default=[],
        help="Create this S3 bucket if missing (local use; repeatable)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        environment = parse_env_pairs(args.env)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    config = ProvisionConfig(
        function_name=args.function_name,
        zip_path=args.zip_path,
        artifact_bucket=args.artifact_bucket,
        role_arn=args.role_arn,
        rule_name=args.rule_name,
        schedule_expression=args.schedule_expression,
        environment=environment,
        runtime=args.runtime,
        handler=args.handler,
        timeout_seconds=args.timeout,
        memory_mb=args.memory,
        ensure_buckets=tuple(args.ensure_bucket),
    )
    result = provision(
        lambda_client=boto3.client("lambda"),
        events_client=boto3.client("events"),
        s3_client=boto3.client("s3"),
        config=config,
    )
    for key, value in result.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
