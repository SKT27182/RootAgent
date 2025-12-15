# RootAgent

An AI-powered chat agent with code execution capabilities, built with FastAPI (backend) and vanilla JavaScript (frontend).

## Features

- 🤖 **LLM-Powered Agent** - Uses LiteLLM to support multiple providers (OpenAI, Gemini, OpenRouter)
- 💻 **Code Execution** - Safely executes Python code with persistent function definitions
- 💬 **Chat Interface** - Clean UI with markdown rendering and syntax highlighting
- 🔐 **Authentication** - JWT-based user authentication
- 💾 **Persistence** - Redis-backed chat history and session management
- 🐳 **Docker Ready** - Full containerization with Docker Compose

---

## Architecture

### System Overview

```
                         Internet
                             │
                             ▼
                   ┌─────────────────┐
                   │     Nginx       │ Port 80 (public)
                   │    Frontend     │
                   └────────┬────────┘
                            │
         ┌──────────────────┼──────────────────┐
         │                  │                  │
         ▼                  ▼                  ▼
    Static Files       API Routes         WebSocket
    /, *.css, *.js     /health, /auth/*   /chat
         │                  │                  │
         ▼                  └────────┬─────────┘
    Served directly                  │
    from Nginx                       ▼
                            ┌─────────────────┐
                            │     Backend     │ Port 8000 (internal)
                            │     FastAPI     │
                            └────────┬────────┘
                                     │
                                     ▼
                            ┌─────────────────┐
                            │      Redis      │ Port 6379 (internal)
                            │  Sessions/Cache │
                            └─────────────────┘
```

### Docker Network Communication

All services communicate over Docker's internal network:

| Service | Internal Hostname | Port | External Access |
|---------|-------------------|------|-----------------|
| Frontend (Nginx) | `frontend` | 80 | ✅ Exposed |
| Backend (FastAPI) | `backend` | 8000 | ❌ Internal only |
| Redis | `redis` | 6379 | ❌ Internal only |

### Request Flow Example

```
User sends chat message:

1. Browser ──POST /chat──▶ Nginx:80
                              │
2. Nginx proxies to ─────────▶ Backend:8000/chat
                                    │
3. Backend processes:               │
   ├── Validates JWT token          │
   ├── Fetches session from Redis ◀─┼──▶ Redis:6379
   ├── Calls LLM API (external)     │
   ├── Executes code (if needed)    │
   └── Stores response in Redis ◀───┼──▶ Redis:6379
                                    │
4. Response flows back: ◀───────────┘
   Backend ──▶ Nginx ──▶ Browser
```

---

## Quick Start

### 1. Clone and Setup

```bash
git clone <repo-url>
cd RootAgent

# Run setup script (creates venv, installs deps, generates JWT secret)
./setup.sh
```

### 2. Configure Environment

Edit `.env` with your API key:

```env
LLM_API_KEY=your-api-key-here
LLM_MODEL=gemini/gemini-1.5-flash
```

### 3. Run

**Option A: Local Development**
```bash
make dev           # Backend + Redis
make dev-frontend  # Frontend (in another terminal)
```

**Option B: Docker (Recommended)**
```bash
docker compose up --build
```

### 4. Access

- **Frontend**: http://localhost (Docker) or http://localhost:3000 (local)
- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs

---

## Project Structure

```
RootAgent/
├── backend/
│   ├── app/
│   │   ├── agent/          # LLM agent logic
│   │   ├── core/           # Config, constants
│   │   ├── models/         # Pydantic schemas
│   │   ├── routers/        # API endpoints
│   │   ├── services/       # Redis, Auth services
│   │   └── main.py         # FastAPI app
│   ├── tests/
│   └── Dockerfile
├── frontend/
│   ├── index.html
│   ├── app.js
│   └── Dockerfile
├── docker-compose.yml
├── Makefile
└── setup.sh
```

---

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `LLM_API_KEY` | API key for LLM provider | *required* |
| `LLM_MODEL` | Model name (LiteLLM format) | `openrouter/amazon/nova-2-lite-v1:free` |
| `JWT_SECRET_KEY` | Secret for JWT signing | *auto-generated* |
| `JWT_EXPIRATION_HOURS` | Token validity | `24` |
| `REDIS_HOST` | Redis server host | `localhost` |
| `REDIS_PORT` | Redis server port | `6379` |
| `REDIS_PASSWORD` | Redis password (optional) | - |
| `LOG_LEVEL` | Logging level | `info` |

---

## Makefile Commands

```bash
make help          # Show all commands

# Docker
make build         # Build images
make up            # Start all services
make down          # Stop all services
make logs          # View logs

# Local Development
make install       # Install dependencies
make dev           # Run backend + Redis
make dev-frontend  # Serve frontend
make dev-stop      # Stop local services

# Testing
make test          # Run tests
make test-cov      # Run with coverage
```

---

## Production Deployment

### Docker Swarm with Secrets

For production, use Docker Secrets instead of `.env` for sensitive values:

```bash
# Create secrets
echo "your-jwt-secret" | docker secret create jwt_secret_key -
echo "your-llm-key" | docker secret create llm_api_key -

# Deploy stack
docker stack deploy -c docker-compose.yml rootagent
```

### Generating a Secure JWT Secret

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

> ⚠️ **Important**: Never use the default JWT secret in production!

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/auth/register` | POST | Register new user |
| `/auth/login` | POST | Login, get JWT |
| `/auth/me` | GET | Get current user |
| `/chat/sessions` | GET | List user sessions |
| `/chat/sessions/{id}` | GET | Get session history |
| `/chat/sessions/{id}` | DELETE | Delete session |
| `/chat/ws/{session_id}` | WS | Chat WebSocket |

---

## Development

### Running Tests

```bash
make test
```

### Code Structure

- **Agent**: ReAct-style reasoning loop with code execution
- **LLM Client**: Uses LiteLLM for provider-agnostic completions
- **Redis Store**: Async session and chat history management
- **Auth Service**: JWT creation/validation with bcrypt passwords

---

## License

MIT License - see [LICENSE](LICENSE)
