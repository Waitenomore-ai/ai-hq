import hmac
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from redis import Redis
from redis.exceptions import RedisError

from ai_hq.auth.dependencies import SESSION_COOKIE, encode_session_cookie, resolve_request_session
from ai_hq.auth.passwords import verify_password
from ai_hq.auth.rate_limit import LoginRateLimiter
from ai_hq.auth.sessions import create_session, revoke_session
from ai_hq.config import Settings

_TEMPLATE_ENV = Environment(
    loader=FileSystemLoader(Path(__file__).with_name("templates")),
    autoescape=select_autoescape(["html", "xml"]),
)


def external_path(settings: Settings, path: str) -> str:
    root = settings.root_path.rstrip("/")
    if path == "/":
        return f"{root}/"
    return f"{root}/{path.lstrip('/')}"


def _render(name: str, **context) -> HTMLResponse:
    template = _TEMPLATE_ENV.get_template(name)
    return HTMLResponse(template.render(**context))


def _client_identity(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _origin_is_allowed(request: Request, settings: Settings) -> bool:
    if not settings.is_production:
        return True
    origin = request.headers.get("origin")
    if not origin:
        return False
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.headers.get("host", ""))
    return hmac.compare_digest(origin.rstrip("/"), f"{scheme}://{host}".rstrip("/"))


def install_web_routes(
    app: FastAPI,
    *,
    settings: Settings,
    session_factory,
    redis_client: Redis,
) -> None:
    limiter = LoginRateLimiter(redis_client)

    @app.get("/login", response_class=HTMLResponse)
    def login_page():
        return _render(
            "login.html",
            root_path=settings.root_path.rstrip("/"),
            error=None,
        )

    @app.post("/login", response_class=HTMLResponse)
    def login(request: Request, password: str = Form(...)):
        if not _origin_is_allowed(request, settings):
            return HTMLResponse("Forbidden", status_code=403)

        identity = _client_identity(request)
        try:
            if limiter.is_blocked(identity):
                return _render(
                    "login.html",
                    root_path=settings.root_path.rstrip("/"),
                    error="Too many attempts. Try again later.",
                )
        except RedisError:
            return HTMLResponse("Authentication temporarily unavailable", status_code=503)

        encoded_hash = settings.admin_password_hash or ""
        if not verify_password(password, encoded_hash):
            try:
                limiter.record_failure(identity)
            except RedisError:
                return HTMLResponse("Authentication temporarily unavailable", status_code=503)
            response = _render(
                "login.html",
                root_path=settings.root_path.rstrip("/"),
                error="Invalid credentials",
            )
            response.status_code = 401
            return response

        try:
            limiter.clear(identity)
        except RedisError:
            return HTMLResponse("Authentication temporarily unavailable", status_code=503)

        with session_factory() as db:
            raw_token, _record = create_session(
                db,
                lifetime_hours=settings.session_lifetime_hours,
            )
            db.commit()

        signed_cookie = encode_session_cookie(raw_token, settings.session_secret or "")
        response = RedirectResponse(external_path(settings, "/"), status_code=303)
        response.set_cookie(
            SESSION_COOKIE,
            signed_cookie,
            max_age=settings.session_lifetime_hours * 3600,
            httponly=True,
            secure=settings.is_production,
            samesite="lax",
            path=settings.root_path,
        )
        return response

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        with session_factory() as db:
            resolved = resolve_request_session(request, db, settings)
            if resolved is None:
                return RedirectResponse(external_path(settings, "/login"), status_code=303)
            _raw_token, record = resolved
            return _render(
                "home.html",
                root_path=settings.root_path.rstrip("/"),
                csrf_token=record.csrf_token,
            )

    @app.get("/api/session")
    def session_info(request: Request):
        with session_factory() as db:
            resolved = resolve_request_session(request, db, settings)
            if resolved is None:
                return JSONResponse({"error": "Authentication required"}, status_code=401)
            _raw_token, record = resolved
            return {
                "authenticated": True,
                "session_id": record.id,
                "expires_at": record.expires_at.isoformat(),
            }

    @app.post("/logout")
    def logout(request: Request, csrf_token: str = Form(...)):
        if not _origin_is_allowed(request, settings):
            return HTMLResponse("Forbidden", status_code=403)
        with session_factory() as db:
            resolved = resolve_request_session(request, db, settings)
            if resolved is None:
                return JSONResponse({"error": "Authentication required"}, status_code=401)
            raw_token, record = resolved
            if not hmac.compare_digest(csrf_token, record.csrf_token):
                return HTMLResponse("Forbidden", status_code=403)
            revoke_session(db, raw_token)
            db.commit()

        response = RedirectResponse(external_path(settings, "/login"), status_code=303)
        response.delete_cookie(SESSION_COOKIE, path=settings.root_path)
        return response
