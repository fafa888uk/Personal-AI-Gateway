#!/bin/sh
# API container entrypoint: apply DB migrations, then start the gateway.
# DATABASE_URL comes from the compose env file (server-side, never in the
# image). Migrations must stay backward-compatible so a failed deploy can
# roll back to the previous image without a DB restore.
set -e
cd /app
alembic upgrade head
exec uvicorn "gateway.main:create_app" --factory --host 0.0.0.0 --port 8000
