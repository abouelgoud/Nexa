"""FastAPI application entrypoint (OpenAPI docs at /docs)."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from nexa.api.routes import (
    agents,
    analytics,
    auth,
    calls,
    health,
    integrations,
    knowledge,
    phone_numbers,
    tenants,
    test,
    tools,
    voices,
    workflows,
)
from nexa.core.config import get_settings
from nexa.core.db import dispose_engine
from nexa.core.errors import AppError, app_error_handler, friendly_validation_errors
from nexa.core.observability import API_ERRORS, setup_logging, setup_tracing
from nexa.tools.database import dispose_all


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await dispose_all()
    await dispose_engine()


def create_app() -> FastAPI:
    s = get_settings()
    if s.environment != "test":
        setup_logging(s.log_level)
    if s.environment == "production" and s.jwt_secret == "change-me-in-production":
        raise RuntimeError("JWT_SECRET must be set in production")
    app = FastAPI(title=s.app_name, version="0.1.0", lifespan=lifespan,
                  description="Multi-tenant no-code AI voice agent platform API.")
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_credentials=True, allow_methods=["*"],
                       allow_headers=["*"])

    async def _app_error(request: Request, exc: AppError):
        API_ERRORS.labels(exc.code).inc()
        return await app_error_handler(request, exc)

    app.add_exception_handler(AppError, _app_error)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        API_ERRORS.labels("validation_failed").inc()
        return JSONResponse(status_code=422, content={"error": {
            "code": "validation_failed", "message": "Some information is missing or invalid.",
            "details": friendly_validation_errors(exc.errors())}})

    app.include_router(health.router)
    for module in (auth, tenants, agents, workflows, tools, integrations, knowledge, phone_numbers, calls, analytics,
                   test, voices):
        app.include_router(module.router)
    app.include_router(agents.templates_router)
    setup_tracing(app, s.otel_exporter_otlp_endpoint)
    return app


app = create_app()
