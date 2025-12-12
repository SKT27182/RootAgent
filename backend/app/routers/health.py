from fastapi import APIRouter
from backend.app.utils.logger import create_logger
from backend.app.core.config import Config

router = APIRouter(prefix="/health", tags=["Health"])
logger = create_logger(__name__, level=Config.LOG_LEVEL)


@router.get("/")
async def health_check():
    logger.debug("Health check requested.")
    return {"status": "ok"}
