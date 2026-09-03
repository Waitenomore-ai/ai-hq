#!/bin/sh
set -eu
alembic upgrade head
exec uvicorn ai_hq.app:app --host 0.0.0.0 --port 8000
