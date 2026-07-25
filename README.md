# RootAgent

CSV/XLSX-focused coding agent with JWT-authenticated chat runs, PostgreSQL-authoritative
sessions, Redis message history and coordination, MinIO artifact storage, and a React
frontend. Generated PNG/CSV/XLSX files are persisted as structured artifacts; file
bytes and host paths are never placed in persisted LLM history.

## Local development

RootAgent uses the shared Postgres, Redis, MinIO, and `infra-network` supplied by
infra-hub.

```bash
make install
cp backend/.env.example backend/.env
# edit backend/.env and start infra-hub first
make db-bootstrap
make dev-local
```

`db-bootstrap` is an explicit development command: it creates the application
database when needed and then runs `alembic upgrade head`. The API never creates or
alters tables during startup.

- API liveness: `http://localhost:8890/health/live`
- Dependency readiness: `http://localhost:8890/health/ready`
- Frontend: `http://localhost:5145`

Run all local gates from the repository root:

```bash
make lint       # Ruff, ESLint, TypeScript
make test       # pytest, Vitest
make build      # production frontend build
```

## Production topology

```text
central reverse proxy
  ├─ /auth, /chat, /artifacts, /admin, /health and /chat/ws → API
  └─ all frontend paths → nginx SPA

API / cleanup worker
  ├─ PostgreSQL: users, sessions, run idempotency, artifact and cleanup metadata
  ├─ Redis: message history, rate limits, run locks, WS tickets, worker heartbeat
  └─ MinIO: uploaded and generated artifact bytes
```

`docker compose up --build` first runs the one-shot migration service. The API and
cleanup worker start only after migration succeeds; the frontend waits for API
readiness. `/metrics` is intentionally not routed by the supplied frontend and must
remain internal at the central proxy.

The supported public routing layer is the central reverse proxy. It must preserve
WebSocket upgrades for `/chat/ws`, route the API paths above to the backend, and
enforce request/body limits consistent with the application quotas. The frontend
nginx serves static SPA content only.

## Security and executor status

Production configuration is fail-closed for debug mode, weak JWT secrets/algorithms,
placeholder credentials, wildcard/non-HTTPS CORS, local dependency hosts, and missing
executor acknowledgement. WebSockets use exact-Origin validation and single-use,
hashed Redis tickets with a 30-second lifetime.

The local executor is **not a sandbox**. If production uses
`EXECUTOR_BACKEND=local`, `ALLOW_UNSAFE_LOCAL_EXECUTOR=true` is mandatory. Startup
logs a critical warning and readiness exposes the acknowledged critical risk. Python
checks cannot stop native libraries from accessing host files, secrets, network, or
process resources. Public deployments remain critically exposed until an isolated
executor is implemented.

`EXECUTOR_BACKEND=grpc` is deliberately a non-operational compatibility stub. It
validates settings, returns stable `sandbox_unavailable` errors, and keeps readiness
unhealthy. See [sandbox protocol v1](docs/sandbox-protocol-v1.md).

## Artifact and run policy

- Inputs: CSV or XLSX, maximum 50 MiB, selected per authenticated session.
- Outputs: PNG/CSV/XLSX, maximum 20 files, 50 MiB/file and 100 MiB/run.
- Generated CSV/XLSX can be explicitly selected later; generated PNG cannot.
- Each message gets a fresh private `0700` workspace and interpreter state.
- A client UUID `request_id` makes HTTP/WS execution idempotent and recoverable.
- Session deletion is idempotent. Durable cleanup jobs reconcile Redis, MinIO, and
  executor workspace cleanup after metadata deletion.

The API and cleanup worker intentionally have separate bounded `/tmp` tmpfs mounts.
Normal local workspaces are destroyed in the API's `finally` path; an API-container
crash destroys its private tmpfs as part of container restart. Cleanup jobs retain
workspace IDs for reconciliation and the future remote executor, but the worker does
not—and cannot—reach another container's private tmpfs.

## Deployment checklist

1. Set `ENVIRONMENT=production`, `DEBUG=false`, exact HTTPS CORS/public URLs, strong
   unique secrets, and non-local service endpoints.
2. If any previously built or distributed backend image may have contained
   `backend/.env`, rotate **all** Postgres, Redis, MinIO, JWT, LLM, SMTP/proxy, and
   related credentials before deployment. Treat rotation as mandatory, not optional.
3. Run the one-shot migration and require `/health/ready` before sending traffic.
4. Keep `/metrics` private and configure the central proxy for authenticated API and
   WebSocket routing.
5. Record acceptance of the local-executor critical risk or leave gRPC mode
   intentionally unavailable until a real isolated runtime and contract tests exist.

## Repository layout

```text
backend/                  FastAPI, Alembic, executor contracts and worker
frontend/                 React/Vite client and hardened nginx image
docs/sandbox-protocol-v1.md
docker-compose.yml        migration, API, cleanup worker and frontend
.github/workflows/ci.yml  quality, migration, security and image gates
```
