#!/bin/sh
# Applies pending Alembic migrations before starting the API process.
# Running this here (rather than as a separate compose step) keeps
# `docker compose up` a true one-command start for local/demo use; a
# real production rollout would run migrations as its own release step
# ahead of a multi-replica deployment instead of on every container boot.
set -e

echo "[entrypoint] Running database migrations..."
alembic upgrade head

echo "[entrypoint] Starting: $*"
exec "$@"
