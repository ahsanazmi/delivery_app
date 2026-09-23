import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import setup_logging
from app.db.session import SessionLocal
from app.ws.manager import manager

setup_logging()
logger = logging.getLogger(__name__)

def _should_enable_docs(environment: str) -> bool:
    """Production Payment Readiness (Phase 40) — the interactive API
    docs (Swagger UI / ReDoc) are a convenience for development, not
    something a production deployment should expose publicly: they
    enumerate every route, request/response shape, and (via "Try it
    out") let anyone probe the live API surface directly from a
    browser. `openapi_url=None` also disables docs_url/redoc_url
    automatically, since both are generated from that same schema. A
    small standalone function, rather than an inline expression, so
    the decision is unit-testable without constructing a whole second
    FastAPI app."""
    return environment != "production"


_docs_enabled = _should_enable_docs(settings.ENVIRONMENT)


@asynccontextmanager
async def lifespan(app: FastAPI):
    manager.bind_loop(asyncio.get_running_loop())
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json" if _docs_enabled else None,
    lifespan=lifespan,
    debug=settings.DEBUG,
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Logging & Error Handling (Phase 26) — every unexpected exception now
    # reaches a server-side log with its full traceback (exc_info=exc),
    # where an operator can actually see it — previously this only ever
    # reached Uvicorn's raw stderr dump, with no structure and no guarantee
    # anyone was capturing it. The client-facing response is unchanged from
    # FastAPI's own default (generic message, same 500, no exception text,
    # no traceback, no file paths) — see
    # test_an_unhandled_exception_returns_a_generic_500_never_leaking_internals
    # for the client-facing contract this must never regress.
    logger.error("Unhandled exception on %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)

@app.get("/")
async def root():
    return {"message": "Say Hi Chai FastAPI backend", "docs": "/docs" if _docs_enabled else None}


@app.get("/health")
async def health():
    """Production Payment Readiness (Phase 40) — a liveness/readiness
    check for a load balancer or orchestrator, previously absent
    entirely. Deliberately unauthenticated (standard practice for a
    health check; it reveals no sensitive information) and confirms the
    one dependency actually worth confirming here — a real database
    round trip, not just "the process is running," since a backend that's
    up but can't reach Postgres is not actually healthy."""
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Health check failed: database unreachable")
        return JSONResponse(status_code=503, content={"status": "unhealthy", "database": "unreachable"})
    return {"status": "ok"}
