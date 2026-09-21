"""AWS Lambda entrypoints (inbound adapters, like ``app.api`` for HTTP).

Runtime adaptation lives here, in the package ``__init__``, because it must
run before anything reads (and caches) ``app.core.config.Settings``.

The Lambda filesystem is read-only except ``/tmp``, but report exports are
written under ``REPORTS_LOCAL_DIR`` (default ``./report_exports``). That is a
property of the Lambda runtime, not something each deployment should have
to remember to configure — so when running inside Lambda (the runtime always
sets ``AWS_LAMBDA_FUNCTION_NAME``) default it to ``/tmp``. An explicit
``REPORTS_LOCAL_DIR`` still wins. The durable copy of every export is the
S3 mirror anyway; ``/tmp`` is only the staging area.
"""

import os

if os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
    os.environ.setdefault("REPORTS_LOCAL_DIR", "/tmp/report_exports")
