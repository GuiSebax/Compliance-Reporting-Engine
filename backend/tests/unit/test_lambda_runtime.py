"""The Lambda package adapts to Lambda's read-only filesystem.

Run in a subprocess: ``Settings`` is cached per process, so the only honest
way to test "what does a fresh Lambda cold start see" is a fresh interpreter.
"""

from __future__ import annotations

import os
import subprocess
import sys

PROBE = (
    "import app.lambda_handlers; "
    "from app.core.config import get_settings; "
    "print(get_settings().reports_local_dir)"
)


def _reports_dir_seen_by_fresh_process(extra_env: dict[str, str]) -> str:
    env = {k: v for k, v in os.environ.items() if k not in ("REPORTS_LOCAL_DIR",)}
    env.pop("AWS_LAMBDA_FUNCTION_NAME", None)
    env.update(extra_env)
    result = subprocess.run(
        [sys.executable, "-c", PROBE], env=env, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def test_inside_lambda_exports_default_to_tmp():
    seen = _reports_dir_seen_by_fresh_process({"AWS_LAMBDA_FUNCTION_NAME": "compliance-report"})
    assert seen == "/tmp/report_exports"


def test_explicit_setting_wins_inside_lambda():
    seen = _reports_dir_seen_by_fresh_process(
        {"AWS_LAMBDA_FUNCTION_NAME": "compliance-report", "REPORTS_LOCAL_DIR": "/mnt/efs/exports"}
    )
    assert seen == "/mnt/efs/exports"


def test_outside_lambda_the_normal_default_is_untouched():
    assert _reports_dir_seen_by_fresh_process({}) == "./report_exports"
