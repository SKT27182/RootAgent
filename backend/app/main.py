import os
import secrets
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from backend.app.routers import health, chat, document, auth
from backend.app.core.config import Config
from backend.app.utils.logger import create_logger

logger = create_logger(__name__, level=Config.LOG_LEVEL)


security = HTTPBasic()


def verify(credentials: HTTPBasicCredentials = Depends(security)):
    username = os.getenv("SWAGGER_USERNAME")
    password = os.getenv("SWAGGER_PASSWORD")

    correct_username = secrets.compare_digest(credentials.username, username)
    correct_password = secrets.compare_digest(credentials.password, password)

    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )
    return True


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Application starting up...")
    yield
    # Shutdown
    logger.info("Application shutting down...")


# Disable default docs in production
app = FastAPI(
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    title="RootAgent API",
    lifespan=lifespan,
)


@app.get("/docs", include_in_schema=False)
def custom_docs(auth: bool = Depends(verify)):
    return get_swagger_ui_html(openapi_url="/openapi.json", title="Secured API Docs")


@app.get("/openapi.json", include_in_schema=False)
async def get_openapi(auth: bool = Depends(verify)):
    return app.openapi()


# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(health.router, tags=["Health"])
app.include_router(chat.router, tags=["Chat"])
app.include_router(document.router, tags=["Document"])
app.include_router(auth.router, tags=["Authentication"])

if __name__ == "__main__":
    import uvicorn

    logger.info("Starting Uvicorn server...")
    uvicorn.run("backend.app.main:app", host="0.0.0.0", port=8000, reload=True)
