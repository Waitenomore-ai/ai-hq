FROM python:3.12-slim

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

CMD ["/app/docker/entrypoint-web.sh"]
