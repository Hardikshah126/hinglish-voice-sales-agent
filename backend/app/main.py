"""FastAPI application factory."""

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.api import benchmark, conversations, evaluations, system, voice
from app.benchmark.runner import mark_interrupted_runs
from app.config import get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging, get_logger
from app.db.session import get_sessionmaker
from app.scenarios.loader import seed_scenarios

log = get_logger(__name__)


def _error(status: int, code: str, message: str, request: Request, **extra) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    body = {"error": {"code": code, "message": message, "request_id": request_id, **extra}}
    return JSONResponse(body, status_code=status)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    try:
        factory = get_sessionmaker()
        interrupted = mark_interrupted_runs(factory)
        with factory() as db:
            seed_scenarios(db)
            db.commit()
        log.info(
            "startup_complete",
            extra={"llm_real": settings.llm_is_real, "interrupted": interrupted},
        )
    except SQLAlchemyError:
        log.error("startup_database_unavailable")
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Hinglish Voice Sales Agent",
        version="0.1.0",
        description="Voice sales agent for FlowDesk with a prompt-strategy evaluation harness.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = uuid.uuid4().hex[:12]
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        if request.url.path != "/health":
            log.info(
                "http_request",
                extra={
                    "request_id": request.state.request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                },
            )
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        if exc.status_code >= 500:
            log.error(
                "app_error",
                extra={"code": exc.code, "request_id": request.state.request_id},
                exc_info=exc.__cause__ is not None,
            )
        return _error(exc.status_code, exc.code, exc.message, request)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        details = [
            {"field": ".".join(str(p) for p in e["loc"] if p != "body"), "issue": e["msg"]}
            for e in exc.errors()
        ]
        return _error(422, "validation_error", "Invalid request.", request, details=details)

    @app.exception_handler(SQLAlchemyError)
    async def database_error_handler(request: Request, exc: SQLAlchemyError):
        log.error(
            "database_error",
            extra={"error_type": type(exc).__name__, "request_id": request.state.request_id},
        )
        return _error(
            503, "database_error", "A database error occurred. Please try again.", request
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        log.error(
            "unhandled_exception",
            extra={"error_type": type(exc).__name__, "request_id": request.state.request_id},
            exc_info=True,
        )
        return _error(500, "internal_error", "Something went wrong on our side.", request)

    for module in (system, voice, conversations, evaluations, benchmark):
        app.include_router(module.router)
    return app


app = create_app()
