import secrets
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.core.config import settings
from app.db.postgres import close_db, init_db
from app.routers import admin, artifacts, auth, chat, health
from app.utils.logger import create_logger

logger = create_logger(__name__, level=settings.log_level)
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
    logger.info("Application starting up...")
    await init_db()
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
