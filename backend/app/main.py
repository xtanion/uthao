import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from . import db, migrations
from .config import get_settings
from .routers import auth, issues, media, me, notifications, stats, users, webhooks

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

FIELD_LABELS = {
    "lat": "latitude",
    "lng": "longitude",
    "radius_m": "radius",
    "client_report_id": "report id",
}


def _readable(error: dict) -> str:
    location = [str(part) for part in error.get("loc", ()) if part not in ("body", "query", "path")]
    field = FIELD_LABELS.get(location[-1] if location else "", location[-1] if location else "request")
    message = error.get("msg", "is not valid")
    message = message.removeprefix("Value error, ")
    if error.get("type") == "missing":
        return f"{field} is required."
    return f"{field}: {message[0].lower() + message[1:] if message else 'is not valid'}."


@asynccontextmanager
async def lifespan(app: FastAPI):
    if get_settings().auto_migrate:
        await migrations.upgrade_head()
    yield
    await db.dispose()


DEFAULT_SECRET = "development-only-secret-key-replace-before-deploying"


def create_app() -> FastAPI:
    settings = get_settings()
    if settings.environment != "development" and settings.secret_key == DEFAULT_SECRET:
        raise RuntimeError(
            "SECRET_KEY is still the development default. Set a real one before "
            f"running with ENVIRONMENT={settings.environment}."
        )
    if not settings.is_local and settings.otp_debug_code:
        raise RuntimeError(
            "OTP_DEBUG_CODE is set. It accepts one code for every phone number, "
            "so anybody could sign in as anybody. Unset it before running with "
            f"ENVIRONMENT={settings.environment}."
        )

    if not settings.is_local and not settings.storage_configured:
        raise RuntimeError(
            "R2 is not configured. Photos would be written to the container's "
            "own disk and lost on the next deploy. Set R2_ACCESS_KEY_ID and "
            f"its siblings before running with ENVIRONMENT={settings.environment}."
        )

    # The interactive docs describe every endpoint and every field.
    docs = settings.is_local or settings.public_docs
    app = FastAPI(
        title="fihy",
        summary="Report and independently confirm public civic issues.",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        """The app renders `detail` verbatim, so a single sentence goes out
        rather than FastAPI's default list of error objects."""
        errors = exc.errors()
        detail = _readable(errors[0]) if errors else "That request was not valid."
        return JSONResponse(
            status_code=422,
            content={"detail": detail},
        )

    app.include_router(auth.router)
    app.include_router(issues.router)
    app.include_router(me.router)
    app.include_router(notifications.router)
    app.include_router(stats.router)
    app.include_router(users.router)
    app.include_router(webhooks.router)
    app.include_router(media.router)

    @app.get("/health", include_in_schema=False)
    async def health() -> JSONResponse:
        """Touches the database. Without that a pod whose connection pool has
        died reports healthy and keeps taking traffic."""
        detail: dict[str, object] = {
            "environment": settings.environment,
            "storage": "r2" if settings.storage_configured else "local",
            "summaries": "on" if settings.ai_summary_configured else "off",
            "mail": "on" if settings.mail_configured else "off",
        }
        try:
            async with db.sessionmaker()() as session:
                await session.execute(text("SELECT 1"))
        except Exception:
            log.exception("health check could not reach the database")
            return JSONResponse(
                status_code=503, content={"status": "degraded", "database": "down", **detail}
            )
        return JSONResponse(content={"status": "ok", "database": "up", **detail})

    return app


app = create_app()
