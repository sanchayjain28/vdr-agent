from __future__ import annotations

import logging
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.core.routers import health_router, topics_router, documents_router
from app.logging import configure_logging
from app.startup import lifespan


def create_app() -> FastAPI:
    """Construct the FastAPI application."""
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = logging.getLogger(__name__)

    app = FastAPI(
        title="VDR Agent Service API",
        description="AI summary and fitment pipeline for ESG VDR documents",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
        root_path="/vdr-agent",
    )

    app.state.settings = settings

    # TODO: Restrict wildcard CORS once frontend origin is finalised.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        body = await request.body()
        try:
            decoded = body.decode("utf-8") if body else ""
        except Exception:
            decoded = str(body)
        logger.error(
            "Validation failed path=%s errors=%s body=%s",
            request.url.path,
            exc.errors(),
            decoded,
        )
        return JSONResponse(status_code=422, content={"detail": exc.errors()})

    app.include_router(health_router)
    app.include_router(topics_router)
    app.include_router(documents_router)
    return app


app = create_app()

LOGGER = logging.getLogger(__name__)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log every request and response with timing."""
    start = perf_counter()
    LOGGER.info("HTTP %s %s incoming", request.method, request.url.path)
    try:
        response = await call_next(request)
    except Exception as exc:
        duration_ms = (perf_counter() - start) * 1000
        LOGGER.exception(
            "HTTP %s %s failed duration=%.2fms error=%s",
            request.method,
            request.url.path,
            duration_ms,
            exc,
        )
        raise
    duration_ms = (perf_counter() - start) * 1000
    LOGGER.info(
        "HTTP %s %s completed status=%s duration=%.2fms",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


__all__ = ["app", "create_app"]
