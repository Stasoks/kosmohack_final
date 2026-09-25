from __future__ import annotations

import json
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text

from backend.app.api import admin, analytics, auth, demo, events, integrations, items, nonconformances, risk, routes
from backend.app.errors import TraceQError
from backend.app.persistence.database import SessionLocal
from backend.app.persistence.models import SecurityAlert
from backend.app.projections.rebuild import recover_stale_projections
from backend.app.security.audit import write_audit
from backend.app.settings import get_settings


settings = get_settings()
logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO), format="%(message)s")
logger = logging.getLogger("traceq")


@asynccontextmanager
async def lifespan(_: FastAPI):
    db = SessionLocal()
    try:
        recovered = recover_stale_projections(db, settings)
        logger.info(json.dumps({"event": "startup_recovery", "recovered_items": len(recovered)}))
    except Exception as exc:
        db.rollback()
        logger.error(
            json.dumps({"event": "startup_recovery_failed", "error_type": type(exc).__name__})
        )
    finally:
        db.close()
    yield


app = FastAPI(
    title="TRACE-Q API",
    version="0.1.0",
    docs_url="/docs" if settings.demo_mode else None,
    redoc_url=None,
    lifespan=lifespan,
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-Id", str(uuid.uuid4()))[:64]
    request.state.request_id = request_id
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    principal = getattr(request.state, "principal", None)
    logger.info(
        json.dumps(
            {
                "event": "http_request",
                "request_id": request_id,
                "user_id": str(principal.user_id) if principal else None,
                "source_id": request.headers.get("X-Source-Id"),
                "endpoint": request.url.path,
                "method": request.method,
                "status": response.status_code,
                "duration_ms": duration_ms,
            },
            ensure_ascii=False,
        )
    )
    response.headers["X-Request-Id"] = request_id
    return response


@app.exception_handler(TraceQError)
async def traceq_error_handler(request: Request, exc: TraceQError):
    if exc.code in {"FORBIDDEN", "FRESH_AUTH_REQUIRED", "SESSION_REVOKED"}:
        principal = getattr(request.state, "principal", None)
        db = SessionLocal()
        try:
            write_audit(
                db,
                action="forbidden_action_attempt",
                outcome="denied",
                actor_user_id=principal.user_id if principal else None,
                session_id=principal.session_id if principal else None,
                target_type="endpoint",
                target_id=request.url.path,
                request_id=getattr(request.state, "request_id", None),
            )
            db.add(SecurityAlert(
                alert_type="RBAC_DENIED" if exc.code == "FORBIDDEN" else "CRITICAL_ACTION_DENIED",
                severity="MEDIUM", target_type="endpoint", target_id=request.url.path,
                details={"error_code": exc.code},
            ))
            db.commit()
        finally:
            db.close()
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "request_id": getattr(request.state, "request_id", None),
            }
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, _: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "REQUEST_VALIDATION_ERROR",
                "message": "Request validation failed",
                "request_id": getattr(request.state, "request_id", None),
            }
        },
    )


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception):
    logger.exception(
        json.dumps(
            {
                "event": "unhandled_error",
                "request_id": getattr(request.state, "request_id", None),
                "error_type": type(exc).__name__,
            }
        )
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An internal error occurred",
                "request_id": getattr(request.state, "request_id", None),
            }
        },
    )


@app.get("/health/live", tags=["health"])
def live():
    return {"status": "alive"}


@app.get("/health/ready", tags=["health"])
def ready():
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        revision = db.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
        if revision != "20260926_0004":
            return JSONResponse(status_code=503, content={"status": "not_ready", "reason": "migration"})
        return {"status": "ready", "migration": revision, "crypto_profile": "classic-v1"}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "not_ready", "reason": "database"})
    finally:
        db.close()


app.include_router(auth.router)
app.include_router(events.router)
app.include_router(items.router)
app.include_router(nonconformances.router)
app.include_router(routes.router)
app.include_router(analytics.router)
app.include_router(integrations.router)
app.include_router(risk.router)
app.include_router(admin.router)
admin.register_demo_routes(app, settings)
if settings.demo_mode:
    app.include_router(demo.router)
