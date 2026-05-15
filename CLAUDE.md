# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DocuMind is an AI-powered document intelligence platform with RAG (Retrieval-Augmented Generation) using a custom **PageIndex** engine — a vectorless, reasoning-based approach that builds hierarchical tree indexes from documents instead of using vector similarity search. It supports multi-tenant workspaces, AI chat with source citations, and real-time response quality evaluation via DeepEval.

## Development Commands

### Running the Stack

```bash
./setup.sh          # First-time setup: AWS SSO login, S3 bucket creation, Docker startup
make up             # Start all services (Docker Compose)
make down           # Stop all services
make build          # Rebuild and restart all services
make reset          # Hard reset — tears down volumes and rebuilds
make logs           # Tail logs for all services
make shell-backend  # Bash shell into backend container
make shell-db       # PostgreSQL CLI (psql)
```

### Frontend

```bash
cd frontend
npm run dev     # Vite dev server on port 5180
npm run build   # TypeScript compile + production build
npm run lint    # ESLint (zero-warnings policy)
```

### Backend Tests

```bash
cd backend
pytest                                    # Run all tests
pytest tests/test_auth.py                 # Run a single test file
pytest tests/test_auth.py::test_login     # Run a single test
pytest -k "tree"                          # Run tests matching a pattern
pytest tests/eval/                        # RAG quality eval tests (require AWS)
```

Tests use mock LLM providers — no real AWS calls unless running `tests/eval/`.

### Database Migrations

```bash
# Inside backend container or with virtualenv active
alembic upgrade head          # Apply all migrations
alembic revision --autogenerate -m "description"  # Generate new migration
alembic downgrade -1          # Rollback last migration
```

Migrations run automatically on backend container startup.

## Architecture

### Services (docker-compose.yml)

| Service | Port | Purpose |
|---|---|---|
| `postgres` | 5440 | PostgreSQL 15 — primary database |
| `redis` | 6380 | Redis 7 — Celery broker + result backend |
| `backend` | 8010 | FastAPI async API server |
| `celery-worker` | — | 8 workers on `default` + `eval_queue` |
| `frontend` | 5180 | Vite React dev server |

### Backend Structure (`backend/app/`)

- **`core/config.py`** — Pydantic Settings; all env vars are declared here
- **`core/database.py`** — AsyncSessionLocal factory (asyncpg driver)
- **`core/security.py`** — JWT encode/decode, role hierarchy (`viewer < editor < admin`)
- **`models/`** — SQLAlchemy 2.0 ORM models; workspace isolation is enforced by filtering all queries on `workspace_id`
- **`api/routes/`** — FastAPI routers; auth at `/auth/*`, everything else at `/api/v1/*`
- **`services/pageindex/`** — Core RAG engine (see below)
- **`services/llm/`** — LLM provider abstraction; `LLMProvider` protocol with Bedrock, Anthropic, and OpenAI implementations
- **`services/document/`** — Text extraction (pdfplumber, python-docx) and async S3 via aiobotocore
- **`services/eval/`** — DeepEval quality metrics + Bedrock-based hallucination judge
- **`workers/`** — Celery tasks: `build_document_tree` (default queue) and `evaluate_response_async` (eval_queue)

### Frontend Structure (`frontend/src/`)

- **`pages/`** — Route-level components: Login, KnowledgeBases, Chat, Library, Settings
- **`components/`** — Shared UI; chat message bubbles, PDF viewer, citation badges, tree explorer, quality monitor
- **`api/`** — Axios-based HTTP client functions
- **`stores/`** — Zustand stores: `chatStore`, `documentStore`, `uiStore`
- **`hooks/`** — Custom hooks for SSE streaming, document polling, etc.

The Vite proxy (`vite.config.ts`) maps `/api` and `/auth` to `http://backend:8010` and `/ws` to the WebSocket endpoint.

### PageIndex RAG Engine (`services/pageindex/`)

Three-stage pipeline invoked synchronously during chat:

1. **`tree_builder.py`** — On document upload (Celery task): extracts text, sends to LLM to build a JSON tree of hierarchical nodes (`node_id`, `title`, `text`, `page_start`, `page_end`, `children`). Stored as JSONB in `document_trees`. Falls back to a single-node tree if LLM response is unparseable.

2. **`tree_navigator.py`** — At query time: sends the merged tree table-of-contents (up to 50 nodes) + user query to LLM. Returns `selected_node_ids` (up to 10) + confidence. Multi-document node IDs are prefixed with `doc_id` to avoid collisions.

3. **`answer_generator.py`** — Takes selected node texts + last 5 conversation turns, streams an SSE response with `[citation:N]` markers. A JSON citations block at the end of the response is parsed and stored in `ChatMessage`.

### Quality Evaluation Flow

After every chat response, `evaluate_response_async` is enqueued on `eval_queue`. It runs DeepEval metrics (faithfulness ≥0.85, answer relevancy ≥0.80, contextual precision ≥0.75, contextual recall ≥0.75, hallucination ≤0.15) using Bedrock as the judge. If faithfulness < 0.85 **or** hallucination > 0.15, a transparency disclaimer is injected into the stored message. Evaluation never blocks the user — it's fail-open.

### Authentication

JWT-based. Access tokens expire in 30 min; refresh tokens in 7 days. Both stored in `localStorage`. The `get_current_user` dependency decodes the JWT and fetches the user from DB on every protected request. Role enforcement uses `require_role(required_role)` which checks the hierarchy.

## Key Environment Variables

Defined in `.env` (see `.env.example`):

```
DATABASE_URL         # postgresql+asyncpg://...
REDIS_URL            # redis://localhost:6380/0
CELERY_BROKER_URL    # redis://localhost:6380/1
CELERY_RESULT_BACKEND # redis://localhost:6380/2
SECRET_KEY           # JWT signing key
AWS_PROFILE          # AWS SSO profile name
AWS_REGION           # S3 region
AWS_BEDROCK_REGION   # Bedrock region (may differ from S3)
S3_BUCKET            # Document storage bucket
CORS_ORIGINS         # Comma-separated allowed origins
```

The active Bedrock model is `us.anthropic.claude-sonnet-4-5-20250929-v1:0` — configured in `services/llm/bedrock.py`.

## Adding a New LLM Provider

Implement the `LLMProvider` protocol in `services/llm/provider.py`, add it to `services/llm/`, and wire it into the dependency injection in `api/routes/chat.py`.

## Common Gotchas

- **Port offsets**: Postgres is on 5440 (not 5432) and Redis on 6380 (not 6379) to avoid conflicts with local instances.
- **Celery queues**: Tree building uses `default` queue; eval uses `eval_queue`. Both must be running for full functionality.
- **S3 uploads**: Document uploads are fire-and-forget async — the API responds before upload completes. Status polling is expected from the frontend.
- **Workspace isolation**: Every DB query must filter by `workspace_id` extracted from the JWT. Missing this filter is a multi-tenancy bug.
- **Test env vars**: `conftest.py` sets dummy env vars before app import so Settings() initializes without a real `.env`.
