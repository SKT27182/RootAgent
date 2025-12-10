from fastapi import APIRouter, UploadFile, File
from backend.app.utils.logger import create_logger
from backend.app.core.config import Config

router = APIRouter()
logger = create_logger(__name__, level=Config.LOG_LEVEL)

@router.post("/upload_document")
async def upload_document(file: UploadFile = File(...)):
    logger.info(f"Received document upload: {file.filename} ({file.content_type})")
    # Placeholder for document processing logic
    return {"filename": file.filename, "content_type": file.content_type, "status": "received"}
