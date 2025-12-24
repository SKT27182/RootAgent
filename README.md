# RootAgent

An AI-powered chat agent with code execution capabilities, built with FastAPI (backend) and React/Vite (frontend).

## Features

- 🤖 **LLM-Powered Agent** - Uses LiteLLM to support multiple providers (OpenAI, Gemini, OpenRouter)
- 💻 **Code Execution** - Safely executes Python code in containerized sandbox with persistent function definitions
- 📊 **Chart Generation** - Generate matplotlib plots and visualizations inline
- 📁 **File Upload** - Upload CSV files and images for analysis
- 💬 **Modern Chat Interface** - React-based UI with markdown rendering and syntax highlighting
- 🔐 **Authentication** - JWT-based user authentication
- 💾 **Persistence** - Redis-backed chat history and session management
- 🌙 **Dark/Light Mode** - Theme toggle support
- 🐳 **Docker Ready** - Full containerization with Docker Compose

---

## Tech Stack

### Frontend
- **React 19** with TypeScript
- **Vite** for fast development and building
- **Tailwind CSS** for styling
- **Radix UI** for accessible components
- **React Markdown** with GFM support

### Backend
- **FastAPI** with async support
- **LiteLLM** for LLM provider abstraction
- **Redis** for session and chat history storage
- **JWT** authentication with bcrypt

---

## Architecture

### System Overview

```
                         Internet
                             │
                             ▼
                   ┌─────────────────┐
                   │     Nginx       │ Port 80/443 (public)
                   │    Frontend     │
                   └────────┬────────┘
                            │
         ┌──────────────────┼──────────────────┐
         │                  │                  │
         ▼                  ▼                  ▼
    Static Files       API Routes         WebSocket
    /, *.css, *.js     /health, /auth/*   /chat/ws
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
                            │      Redis      │ Port 9980 (internal)
                            │  Sessions/Cache │
                            └─────────────────┘
```

### Docker Network Communication

| Service | Internal Hostname | Port | External Access |
|---------|-------------------|------|-----------------|
| Frontend (Nginx) | `frontend` | 80/443 | ✅ Exposed |
| Backend (FastAPI) | `backend` | 8000 | ❌ Internal only |
| Redis | `redis` | 9980 | ❌ Internal only |

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

Copy `.env.example` to `.env` and configure:

```env
LLM_API_KEY=your-api-key-here
LLM_MODEL=gemini/gemini-1.5-flash
```

### 3. Run

**Option A: Docker (Recommended)**
```bash
make up-build          # Build and start in background
make up-build-debug    # Build and start in foreground (with logs)
```

**Option B: Local Development**
```bash
make dev               # Backend + Redis
cd frontend && npm run dev  # Frontend (in another terminal)
```

### 4. Access

- **Frontend**: http://localhost (Docker) or http://localhost:5173 (local dev)
- **API Docs**: http://localhost/docs (requires authentication)

---

## Project Structure

```
RootAgent/
├── backend/
│   ├── app/
│   │   ├── agent/          # LLM agent logic, tools, prompts
│   │   ├── core/           # Config
│   │   ├── models/         # Pydantic schemas
│   │   ├── routers/        # API endpoints (chat, auth, health)
│   │   ├── services/       # Redis store, Auth service
│   │   ├── utils/          # Logger, message formatters
│   │   └── main.py         # FastAPI app
│   ├── tests/
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── components/     # UI components (Radix-based)
│   │   ├── pages/          # Chat, Login pages
│   │   ├── lib/            # Auth context, utilities
│   │   └── App.tsx         # Main app with routing
│   ├── nginx/              # Nginx configuration
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
| `LLM_MODEL` | Model name (LiteLLM format) | `gemini/gemini-1.5-flash` |
| `JWT_SECRET_KEY` | Secret for JWT signing | *auto-generated* |
| `JWT_EXPIRATION_HOURS` | Token validity | `24` |
| `REDIS_HOST` | Redis server host | `redis` |
| `REDIS_PORT` | Redis server port | `9980` |
| `LOG_LEVEL` | Logging level | `INFO` |

---

## Makefile Commands

```bash
make help              # Show all commands

# Docker
make up-build          # Build and start all services
make up-build-debug    # Build and start with logs (foreground)
make down              # Stop all services
make logs              # View logs
make ps                # Show running containers

# Local Development
make install           # Install dependencies
make dev               # Run backend + Redis
make dev-frontend      # Serve frontend
make dev-stop          # Stop local services

# Testing
make test              # Run tests
make test-cov          # Run with coverage
```

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/auth/register` | POST | Register new user |
| `/auth/login` | POST | Login, get JWT |
| `/auth/me` | GET | Get current user |
| `/chat/sessions/{user_id}` | GET | List user sessions |
| `/chat/history/{user_id}/{session_id}` | GET | Get session history |
| `/chat/sessions/{user_id}/{session_id}` | DELETE | Delete session |
| `/chat/ws` | WebSocket | Chat WebSocket |
| `/document/` | POST | Upload document |

---

## Features in Detail

### File Uploads
- **CSV Files**: Upload CSV data for analysis. The agent can read and process the data.
- **Images**: Upload images for vision-capable models to analyze.

### Code Execution
- Python code runs in an isolated environment
- Persistent function definitions across messages
- Support for data visualization with matplotlib

### Agent Tools
- `figure_to_base64`: Convert matplotlib figures to inline images
- `web_search`: Search the web for current information (via Tavily)

---

## Production Deployment

### Docker Compose

```bash
# Build and run in background
make up-build

# View logs
make logs
```

### Security Notes

- Change default JWT secret in production
- Use HTTPS (configure SSL in nginx)
- Set proper CORS origins

---

## License

MIT License - see [LICENSE](LICENSE)
