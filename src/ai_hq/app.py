from collections.abc import Callable

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from ai_hq.health import database_probe as default_database_probe
from ai_hq.health import readiness_payload
from ai_hq.health import redis_probe as default_redis_probe


def create_app(
    *,
    database_probe: Callable[[], bool] = default_database_probe,
    redis_probe: Callable[[], bool] = default_redis_probe,
) -> FastAPI:
    app = FastAPI(title="AI HQ", version="0.1.0")

    @app.get("/health/live")
    def live():
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready():
        status_code, payload = readiness_payload(database_probe(), redis_probe())
        return JSONResponse(status_code=status_code, content=payload)

    return app


app = create_app()
