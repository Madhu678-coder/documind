# DocuMind Architecture

## Overview

DocuMind is an AI document intelligence platform powered by **PageIndex** — a vectorless, reasoning-based RAG engine. Instead of vector similarity search, PageIndex builds hierarchical tree indexes and uses LLM reasoning to navigate documents.

## System Architecture

```
┌─────────────────────────────────────────────────────────┐
│  FRONTEND (React + TypeScript + Vite)                   │
│  Port 5180 │ Vite Proxy → Backend                       │
└──────────────────────┬──────────────────────────────────┘
                       │ REST API + WebSocket
┌──────────────────────▼──────────────────────────────────┐
│  BACKEND (FastAPI + Python)                             │
│  Port 8010 │ Async SQLAlchemy │ Pydantic v2             │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│  PAGEINDEX ENGINE                                       │
│  Tree Builder → Navigator → Answer Generator           │
│  ↕ AWS Bedrock (Claude Sonnet 4.5)                     │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│  EVALUATION (DeepEval + Bedrock)                        │
│  Faithfulness │ Relevancy │ Precision │ Recall          │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│  STORAGE                                                │
│  PostgreSQL │ AWS S3 │ Redis │ Celery (8 workers)      │
└─────────────────────────────────────────────────────────┘
```

## Docker Services

| Service | Purpose | Port |
|---------|---------|------|
| `backend` | FastAPI REST API | 8010 |
| `celery-worker` | Document processing + evaluations (8 workers) | - |
| `postgres` | PostgreSQL database | 5440 |
| `redis` | Cache, Celery broker | 6380 |
| `frontend` | React dev server | 5180 |

## Data Flow

### Document Upload

```
1. User uploads file → Frontend
2. POST /api/v1/documents/upload → Backend
3. Async S3 upload (aiobotocore)
4. Document record created (status: processing)
5. Celery task: build_document_tree.delay(doc_id)
6. Text extraction + LLM tree generation (combined call)
7. Tree stored as JSONB in document_trees
8. Status updated to 'ready'
```

### Chat Query

```
1. User query → Frontend
2. POST /api/v1/chat/sessions/{id}/messages
3. Load document trees from database
4. PageIndex Navigator: LLM selects relevant nodes
5. PageIndex Answer Generator: LLM generates answer with citations
6. Stream response via SSE
7. Async: Celery evaluates with DeepEval
8. Store eval results
```

## Database Schema

### Core Tables
- **workspaces**: Multi-tenant isolation
- **users**: Authentication + roles
- **documents**: Files with processing status
- **document_trees**: Hierarchical indexes (JSONB)
- **knowledge_bases**: Document collections
- **chat_sessions**: Conversations
- **chat_messages**: Messages with citations

### Evaluation Tables
- **eval_results**: DeepEval scores per message
- **eval_config**: Quality thresholds per workspace

## PageIndex Engine

### Three-Stage Pipeline

1. **Tree Builder**: Extracts text → LLM generates hierarchical tree
2. **Tree Navigator**: LLM reasons which nodes are relevant
3. **Answer Generator**: LLM generates answer with citations

### Key Features
- No vector database (pure reasoning)
- Multi-document support
- Context-aware (last 5 turns)
- Citation format: `{ doc_name, section, page, node_id, excerpt }`

## DeepEval Quality Metrics

1. **Faithfulness** (≥0.85): Answer grounded in sources
2. **Answer Relevancy** (≥0.80): Relevant to query
3. **Contextual Precision** (≥0.75): Right nodes ranked high
4. **Contextual Recall** (≥0.75): Context covers answer
5. **Hallucination** (≤0.15): No factual deviation

Low-confidence responses trigger disclaimer.

## Performance Optimizations

- **Async S3 uploads**: aiobotocore for parallel uploads
- **Combined LLM calls**: Single Bedrock call for tree + insights
- **8 Celery workers**: Parallel document processing
- **Vite proxy**: No CORS issues, relative URLs
- **Connection pooling**: PostgreSQL + Redis

## Security

- **Workspace isolation**: All queries scoped to workspace_id
- **JWT authentication**: Access + refresh tokens
- **Role-based access**: Admin, Editor, Viewer
- **Audit trail**: All operations logged
- **Input validation**: Magic bytes + MIME type checks

## AWS Configuration

- **S3 Region**: us-east-1
- **Bedrock Region**: us-east-1
- **Bedrock Model**: us.anthropic.claude-3-5-sonnet-20241022-v2:0
- **Auth**: AWS SSO profile (dev) / IAM role (prod)

## Key Design Decisions

1. **Vectorless RAG**: LLM reasoning over document structure
2. **Async everything**: Celery for tasks, SSE for streaming
3. **Quality-first**: Every response evaluated
4. **Multi-tenant**: Workspace isolation
5. **Single LLM provider**: AWS Bedrock for consistency
6. **Docker-first**: All services containerized

## Monitoring

- Health checks: `/health`, `/health/db`, `/health/redis`
- Structured JSON logging with correlation IDs
- Quality dashboard with eval metrics
- Full audit trail

---

*Last Updated: March 2026*
