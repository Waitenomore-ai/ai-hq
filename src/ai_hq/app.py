from collections.abc import Callable

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from redis import Redis

from ai_hq.config import Settings, get_settings
from ai_hq.db import get_session_factory
from ai_hq.health import database_probe as default_database_probe
from ai_hq.health import readiness_payload
from ai_hq.health import redis_probe as default_redis_probe
from ai_hq.missions.api import install_mission_routes
from ai_hq.web import install_web_routes


def create_app(
    *,
    settings: Settings | None = None,
    session_factory=None,
    redis_client=None,
    database_probe: Callable[[], bool] = default_database_probe,
    redis_probe: Callable[[], bool] = default_redis_probe,
) -> FastAPI:
    app = FastAPI(
        title="AI HQ",
        version="0.1.0",
        root_path=settings.root_path if settings else "",
    )

    @app.get("/health/live")
    def live():
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready():
        status_code, payload = readiness_payload(database_probe(), redis_probe())
        return JSONResponse(status_code=status_code, content=payload)

    if settings is not None:
        factory = session_factory or get_session_factory()
        redis_connection = redis_client or Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        install_web_routes(
            app,
            settings=settings,
            session_factory=factory,
            redis_client=redis_connection,
        )
        install_mission_routes(
            app,
            settings=settings,
            session_factory=factory,
        )

    return app


def create_runtime_app() -> FastAPI:
    return create_app(settings=get_settings())
