import logging
import uuid
import json
import time
from contextlib import asynccontextmanager
from contextvars import ContextVar

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.database import engine

# ── Correlation ID context var ────────────────────────────────────────────────
correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")


# ── Structured JSON logging ───────────────────────────────────────────────────
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_record = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S.%f+00:00"),
            "level": record.levelname,
            "correlation_id": correlation_id_var.get(""),
            "message": record.getMessage(),
            "logger": record.name,
        }
        if record.exc_info:
            log_record["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(log_record)


def setup_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))


access_logger = logging.getLogger("app.access")


# ── Correlation ID middleware ─────────────────────────────────────────────────
class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        cid = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
        token = correlation_id_var.set(cid)
        start = time.monotonic()
        try:
            response: Response = await call_next(request)
            response.headers["X-Correlation-ID"] = cid
            duration_ms = (time.monotonic() - start) * 1000
            access_logger.info(
                json.dumps({
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "+00:00",
                    "level": "INFO",
                    "correlation_id": cid,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": round(duration_ms, 3),
                })
            )
            return response
        finally:
            correlation_id_var.reset(token)


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger = logging.getLogger("app")
    logger.info("DocuMind backend starting up")
    yield
    logger.info("DocuMind backend shutting down")
    await engine.dispose()
    # Close Neo4j driver
    try:
        from app.services.graph.neo4j_client import close_neo4j_driver
        await close_neo4j_driver()
    except Exception:
        pass


# ── App factory ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="DocuMind API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Correlation ID
app.add_middleware(CorrelationIdMiddleware)


# ── Global exception handler ──────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger = logging.getLogger("app")
    logger.exception("Unhandled exception")
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected error occurred.",
                "correlation_id": correlation_id_var.get(""),
            }
        },
    )


# ── Routers ───────────────────────────────────────────────────────────────────
from app.api.routes import auth, health, documents, knowledge_bases
from app.api.routes.chat import router as chat_router, ws_router
from app.api.routes.insights import router as insights_router
from app.api.routes.eval import router as eval_router
from app.api.routes.model_providers import router as model_providers_router
from app.api.routes.retrieval import router as retrieval_router
from app.api.routes.wiki_pages import router as wiki_pages_router
from app.api.routes.graph import router as graph_router
from app.api.routes.openkb import router as openkb_router
app.include_router(health.router)
app.include_router(auth.router)                    # /auth/login, /auth/logout (legacy)
app.include_router(auth.router, prefix="/api/v1")  # /api/v1/auth/refresh (frontend expects this)
app.include_router(documents.router, prefix="/api/v1")
app.include_router(knowledge_bases.router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")
app.include_router(ws_router)
app.include_router(insights_router, prefix="/api/v1")
app.include_router(eval_router, prefix="/api/v1")
app.include_router(model_providers_router, prefix="/api/v1")
app.include_router(retrieval_router, prefix="/api/v1")
app.include_router(wiki_pages_router, prefix="/api/v1")
app.include_router(graph_router, prefix="/api/v1")
app.include_router(openkb_router, prefix="/api/v1")
