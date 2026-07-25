import secrets
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.db.postgres import close_db
from app.routers import admin, artifacts, auth, chat, health
from app.utils.logger import create_logger
from app.utils.logging_bridge import (
    configure_third_party_loggers,
    setup_unified_logging,
)
from app.core.metrics import HTTP_DURATION, HTTP_REQUESTS

logger = create_logger(__name__, level=settings.log_level)

# Route uvicorn/SQLAlchemy into the colored + file logging stack.
_log_file = setup_unified_logging(settings.log_level)
configure_third_party_loggers(settings.log_level)
logger.info("Unified logging enabled (backend log: %s)", _log_file)

security = HTTPBasic()


def verify_swagger(credentials: HTTPBasicCredentials = Depends(security)) -> bool:
    username = settings.swagger_username
    password = settings.swagger_password
    if not username or not password:
        raise HTTPException(
            status_code=401,
            detail="Swagger auth not configured",
            headers={"WWW-Authenticate": "Basic"},
        )
    ok_user = secrets.compare_digest(credentials.username, username)
    ok_pass = secrets.compare_digest(credentials.password, password)
    if not (ok_user and ok_pass):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )
    return True


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Re-apply after uvicorn's own logging setup (CLI / reload workers).
    configure_third_party_loggers(settings.log_level)
    logger.info("Application starting up...")
    if settings.environment == "production" and settings.executor_backend == "local":
        logger.critical(
            "UNSAFE LOCAL EXECUTOR ENABLED: public code execution can access host "
            "files and secrets, exhaust resources, and exfiltrate data"
        )
    yield
    await close_db()
    logger.info("Application shutting down...")


app = FastAPI(
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    title="RootAgent API",
    lifespan=lifespan,
)


def _correlation_id(request: Request) -> str:
    value = getattr(request.state, "correlation_id", None)
    return str(value or uuid.uuid4())


@app.middleware("http")
async def add_correlation_id(request: Request, call_next):
    supplied = request.headers.get("X-Correlation-ID")
    try:
        correlation_id = str(uuid.UUID(supplied)) if supplied else str(uuid.uuid4())
    except ValueError:
        correlation_id = str(uuid.uuid4())
    request.state.correlation_id = correlation_id
    started = time.monotonic()
    response = await call_next(request)
    route = getattr(request.scope.get("route"), "path", request.url.path)
    HTTP_REQUESTS.labels(request.method, route, str(response.status_code)).inc()
    HTTP_DURATION.labels(request.method, route).observe(time.monotonic() - started)
    response.headers["X-Correlation-ID"] = correlation_id
    return response


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    correlation_id = _correlation_id(request)
    if isinstance(exc.detail, dict):
        code = str(exc.detail.get("code", "request_failed"))
        message = str(exc.detail.get("message", "The request could not be completed"))
        retryable = bool(exc.detail.get("retryable", False))
    else:
        code = {
            400: "validation_error",
            401: "authentication_failed",
            403: "forbidden",
            404: "not_found",
            409: "conflict",
            413: "upload_too_large",
            415: "upload_type_rejected",
            429: "rate_limited",
            503: "dependency_unavailable",
        }.get(exc.status_code, "request_failed")
        message = str(exc.detail)
        retryable = exc.status_code in {429, 502, 503, 504}
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": code,
            "message": message,
            "retryable": retryable,
            "correlation_id": correlation_id,
            "detail": message,
        },
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.info(
        "Request validation failed correlation_id=%s errors=%s",
        _correlation_id(request),
        exc.errors(),
    )
    return JSONResponse(
        status_code=422,
        content={
            "code": "validation_error",
            "message": "The request is malformed or invalid",
            "retryable": False,
            "detail": "The request is malformed or invalid",
            "correlation_id": _correlation_id(request),
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    correlation_id = _correlation_id(request)
    logger.error(
        "Unhandled request error correlation_id=%s",
        correlation_id,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return JSONResponse(
        status_code=500,
        content={
            "code": "internal_error",
            "message": "Internal server error",
            "retryable": True,
            "detail": "Internal server error",
            "correlation_id": correlation_id,
        },
    )


@app.get("/docs", include_in_schema=False)
def custom_docs(auth: bool = Depends(verify_swagger)):
    return get_swagger_ui_html(openapi_url="/openapi.json", title="Secured API Docs")


@app.get("/openapi.json", include_in_schema=False)
async def get_openapi(auth: bool = Depends(verify_swagger)):
    return app.openapi()


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {
        "service": "RootAgent API",
        "health": "/health",
        "docs": "/docs",
    }


app.include_router(health.router, tags=["Health"])
app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(artifacts.router)
app.include_router(admin.router)
