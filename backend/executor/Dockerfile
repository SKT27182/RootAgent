# =========================
# Executor Container
# =========================
# Minimal, isolated Python environment for safe code execution
FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY executor/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy executor service
COPY executor/executor_service.py .

# Create utils directory for mounted logger
RUN mkdir -p utils

# Create non-root user for additional security
RUN useradd --create-home --shell /bin/bash executor
USER executor

EXPOSE 8001

CMD ["uvicorn", "executor_service:app", "--host", "0.0.0.0", "--port", "8001"]
