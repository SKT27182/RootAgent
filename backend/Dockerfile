FROM ghcr.io/astral-sh/uv:0.11.29@sha256:eb2843a1e56fd9e30c7276ce1a52cba86e64c7b385f5e3279a0e08e02dd058fc AS uv-bin

FROM python:3.12-slim-bookworm@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    API_PORT=8890 \
    BACKEND_LOG_FILE=/tmp/rootagent/backend.log

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 rootagent \
    && useradd --uid 10001 --gid rootagent --create-home --shell /usr/sbin/nologin rootagent

COPY --from=uv-bin /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --format requirements-txt --output-file /tmp/requirements.txt \
    && uv pip install --system --no-cache --requirements /tmp/requirements.txt \
    && rm /tmp/requirements.txt

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY scripts ./scripts

RUN mkdir -p /tmp/rootagent /tmp/rootagent-workspaces \
    && chown -R rootagent:rootagent /tmp/rootagent /tmp/rootagent-workspaces /app

USER 10001:10001
EXPOSE 8890

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${API_PORT}"]
