FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml README.md* ./
COPY src ./src
COPY alembic.ini ./
COPY migrations ./migrations
COPY docker ./docker
RUN pip install --no-cache-dir .
RUN chmod +x /app/docker/entrypoint-web.sh /app/docker/entrypoint-worker.sh

FROM base AS web
CMD ["/app/docker/entrypoint-web.sh"]

FROM base AS worker
RUN pip install --no-cache-dir "soup-cli==0.74.0"
CMD ["/app/docker/entrypoint-worker.sh"]
