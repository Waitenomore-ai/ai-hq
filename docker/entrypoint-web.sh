#!/bin/sh
set -eu
alembic upgrade head
exec uvicorn ai_hq.app:create_runtime_app --factory --host 0.0.0.0 --port 8000
