from fastapi import APIRouter

from app.core.config import settings
from app.utils.logger import create_logger

router = APIRouter(tags=["Health"])
logger = create_logger(__name__, level=settings.log_level)


@router.get("/health")
async def health_check():
    logger.verbose("Health check OK")
    return {"status": "ok"}
