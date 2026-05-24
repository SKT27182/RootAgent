# RootAgent

AI coding agent with JSON-step ReAct loop, Postgres auth, MinIO artifacts, and Redis chat history. Aligned with [infra-hub](https://github.com) and [FlexSearch](../FlexSearch) dev patterns.

## Prerequisites

1. Start **infra-hub** (`make up` in infra-hub) so `infra-network` exists with Postgres, Redis, and MinIO.
2. Create database `rootagent` (or let the app create it on startup via `ensure_database_exists`).
3. Copy `backend/.env.example` → `backend/.env` and align credentials with infra-hub.

## Quick start (local)

```bash
make install          # uv sync + pnpm install
cp backend/.env.example backend/.env   # edit values
make db-migrate       # Alembic migrations
make dev-local        # backend :8890 + frontend :5145
```

- Backend API: http://localhost:8890/health  
- Frontend (Vite): http://localhost:5145 — proxies `/auth`, `/chat`, `/artifacts` to the API  
- Infra-hub admins: log in with your **main_db** credentials (same email/password as infra-hub)

## Docker (app only)

```bash
# infra-hub must be running first
make dev              # docker compose up on infra-network
```

Compose exposes backend `127.0.0.1:8890` and frontend `127.0.0.1:5145`. Route `/auth`, `/chat`, `/artifacts`, `/health` through your **centralized reverse proxy** to the backend; the frontend container serves static files only (no API proxy).

## Architecture

```
Central reverse proxy
        │
        ├──► rootagent-frontend (static)
        └──► rootagent-backend (FastAPI)
                    ├── Postgres (rootagent DB) — users, chats, artifacts metadata
                    ├── Redis — chat message history only
                    └── MinIO — artifact binaries
```

### Key behavior changes

- **Auth:** PostgreSQL + JWT (email login); no Redis auth.
- **Artifacts:** Upload/list/preview/download/delete per chat via `/artifacts/{session_id}`.
- **Agent:** Structured JSON steps (`thinking`, `code`, `final_answer`, `is_final_answer`); no cross-turn function/import memory in Redis.
- **Admin hierarchy:** `INFRA_ADMIN` (any user in infra-hub `main_db.users`) → `ADMIN` (RootAgent-only, promoted by infra admins) → `USER`. Infra details stay in `main_db`; RootAgent stores only a link (`infra_hub_user_id`) plus RootAgent-local users.

## Makefile targets

| Command | Description |
|---------|-------------|
| `make install` | Backend `uv sync` + frontend `pnpm install` |
| `make dev-local` | Run backend + frontend locally with log files |
| `make dev` / `make up` | Docker compose on `infra-network` |
| `make down` | Stop containers and local processes |
| `make db-migrate` | `alembic upgrade head` |
| `make db-shell` | `psql` into infra-postgres / `rootagent` |
| `make test` | Backend pytest |

## Migration note

Redis-backed users from the legacy stack are **not** migrated. Re-register locally or sign in with an infra-hub admin account from `main_db.users`.

## Project layout

```
RootAgent/
├── backend/           # Python package (uv, FastAPI, Alembic)
│   ├── app/
│   ├── alembic/
│   └── pyproject.toml
├── frontend/          # Vite + React
├── docker-compose.yml # backend + frontend on infra-network
└── Makefile
```
