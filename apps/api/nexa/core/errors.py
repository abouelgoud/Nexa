"""Errors carry a business-language message suitable for non-technical users."""

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, details: Any = None, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.details = details
        if code:
            self.code = code


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_failed"


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"


class ServiceUnavailable(AppError):
    status_code = 503
    code = "service_unavailable"


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
    )


def friendly_validation_errors(errors: list[dict]) -> list[dict]:
    """Turn pydantic errors into business-language messages."""
    out = []
    for e in errors:
        loc = [str(p) for p in e.get("loc", []) if p not in ("body",)]
        field = " → ".join(loc) if loc else "value"
        msg = e.get("msg", "is invalid")
        if e.get("type") == "missing":
            msg = "is required"
        elif msg.startswith("Value error, "):
            msg = msg.removeprefix("Value error, ")
        out.append({"field": field, "message": f"{field.replace('_', ' ').capitalize()}: {msg}"})
    return out
