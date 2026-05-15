# DocuMind — Complete Codebase Guide

## What Is DocuMind?

DocuMind is a web application where you upload documents (PDFs, Word files, text files) and then ask questions about them in a chat interface. The AI reads your documents and gives you answers with exact references to where it found the information.

It has 3 different ways to process and search documents:
- **PageIndex** — The AI reads the document and builds a table of contents (tree). At question time, the AI reads the table of contents and picks the right sections.
- **Vector RAG** — The document is split into small pieces (chunks), each piece is converted to numbers (embeddings), and math finds the most similar pieces to your question.
- **Wiki** — The AI reads the document and creates encyclopedia-style wiki pages. When you ask a question, the AI picks the right wiki pages.

---

## Technologies Used

### Frontend (what the user sees in the browser)

**React** — A JavaScript library for building user interfaces. It breaks the page into small reusable pieces called "components." For example, there's a `MessageBubble` component that draws one chat message, and it's reused for every message.

**TypeScript** — A version of JavaScript that adds type checking. Instead of `let name = "hello"`, you write `let name: string = "hello"`. This catches bugs early — if you accidentally try to do math on a name, TypeScript tells you before the code runs.

**Vite** — A tool that takes all the React/TypeScript code and bundles it into files the browser can understand. It also runs a development server on port 5180.

**Tailwind CSS** — A way to style the UI by adding class names directly to HTML elements like `className="text-sm font-bold text-blue-600"`. Each class does one thing: `text-sm` makes text small, `font-bold` makes it bold.

**Zustand** — A state management library. "State" means data that changes over time — like the list of chat messages or whether a file is uploading. Zustand stores this data in one place so all components can access it.

**Axios** — A library for making HTTP requests from the browser to the backend server.

**Lucide** — An icon library. All the small icons (send button, trash can, book icon) come from Lucide.

### Backend (the server that does the work)

**Python** — The programming language the backend is written in.

**FastAPI** — A Python web framework. It receives HTTP requests from the frontend, processes them, and sends back responses. It's "async" — it can handle many requests at the same time.

**SQLAlchemy** — A library that lets Python code talk to the database. Instead of writing raw SQL, you write Python code that SQLAlchemy converts to SQL.

**Pydantic** — A library for data validation. When the frontend sends data, Pydantic checks that it's in the correct format.

**Alembic** — A database migration tool. When you need to add a new column to a table, you create a migration file. Running `alembic upgrade head` applies all changes to the database.

### Database

**PostgreSQL** — A relational database that stores all data in tables (like spreadsheets). Running on port 5440.

**JSONB** — A PostgreSQL column type that stores JSON data. Normal columns store one value. JSONB stores a flexible structure — you can add new fields without changing the table.

**pgvector** — A PostgreSQL extension for storing and searching vectors (lists of numbers). Used for Vector RAG similarity search.

### Background Processing

**Redis** — An in-memory data store used as a message queue. When the backend needs to process a document (which takes minutes), it puts a message in Redis. A Celery worker picks it up. Running on port 6380.

**Celery** — A task queue system. It runs 8 worker processes that pick up tasks from Redis. Tasks include: building document trees, chunking and embedding documents, building wiki pages, and evaluating answer quality.

**Celery Beat** — A scheduler that runs tasks at specific times: re-evaluating messages at 2 AM, cleaning up files at 3 AM.

### Cloud Services

**AWS S3** — Amazon's file storage. Uploaded PDFs are stored here, not in the database.

**AWS Bedrock** — Amazon's managed AI service. When DocuMind needs the AI to do something, it sends a request to Bedrock, which runs Claude Sonnet 4.5.

### Docker

**Docker** — Packages each service into isolated containers. Each container has everything it needs to run.

**docker-compose.yml** — Defines all 5 containers and how they connect. Running `docker-compose up` starts everything.

---

## Infrastructure — What Runs Where

```
User's Browser (http://localhost:5180)
    │
    ▼
Frontend (React + Vite, port 5180)
    Serves HTML/CSS/JS
    Vite proxy forwards /api/v1/* to backend
    │
    ▼
Backend (FastAPI + Python, port 8010)
    Handles all API requests
    Connects to PostgreSQL, Redis, S3
    │
    ├── PostgreSQL (port 5440) — All data lives here
    ├── Redis (port 6380) — Task queue + cache
    ├── Celery Workers (8 processes) — Background document processing
    └── AWS Services — S3 (file storage) + Bedrock (LLM API)
```

---

## Database — All 14 Tables

### Relationship Map

```
workspaces (root — one per organization)
  ├── users (many per workspace)
  ├── knowledge_bases (many per workspace)
  │     ├── documents (many per KB)
  │     │     ├── document_trees (one per doc, PageIndex only)
  │     │     └── document_chunks (many per doc, Vector RAG only)
  │     ├── wiki_pages (many per KB, Wiki mode only)
  │     └── chat_sessions (many per KB)
  │           └── chat_messages (many per session)
  │                 └── eval_results (many per message)
  ├── eval_config (one per workspace)
  ├── model_provider_configs (many per workspace)
  └── audit_logs (many, via user_id)
```


### Table Details

**workspaces** — The root entity for multi-tenancy (multiple organizations sharing one app but can't see each other's data). Fields: id (UUID), name ("Acme Corp"), owner_id (FK to users), settings (JSONB).

**users** — Each user belongs to one workspace and has a role. Fields: id, name, email (unique), hashed_password, role (admin/editor/viewer), workspace_id (FK), created_at.

**knowledge_bases** — A collection of documents. The settings JSONB stores the RAG mode and all configuration. Fields: id, workspace_id (FK), name, description, created_by (FK to users), created_at, settings (JSONB like `{"rag_mode": "vector", "chunk_size": 1000, ...}`).

**documents** — Each uploaded file. Fields: id, workspace_id (FK), kb_id (FK), filename, file_path (S3 key like "workspaces/uuid/uuid.pdf"), file_type (pdf/docx/txt/md), size_bytes, status (uploading/processing/ready/failed), uploaded_by (FK), created_at.

**document_trees** — PageIndex trees. One row per document. Fields: id, document_id (FK, unique), tree_json (JSONB — the entire hierarchical tree), executive_summary, key_entities (JSONB), document_tags (text array), complexity_score (0.0-1.0), llm_model_used, token_count, built_at.

**document_chunks** — Vector RAG chunks. Many rows per document. Fields: id, document_id (FK), kb_id (FK), workspace_id (FK), chunk_index, text, char_start, char_end, page_number, parent_chunk_id (self-referencing FK for parent-child strategy), chunk_metadata (JSONB, currently always empty), embedding (1024-dim vector column), created_at.

**wiki_pages** — LLM-maintained wiki pages. Fields: id, kb_id (FK), workspace_id (FK), title (merge key — unique per KB), summary, content (markdown), page_type (entity/concept/process/event/general), source_doc_ids (JSONB list of document UUIDs), related_titles (text array), llm_model_used, created_at, updated_at.

**chat_sessions** — A conversation tied to one KB and one user. Fields: id, workspace_id (FK), kb_id (FK), user_id (FK), title (auto-generated from first message), created_at.

**chat_messages** — Each message in a conversation. Fields: id, session_id (FK), role (user/assistant), content, citations (JSONB array), reasoning_trace (JSONB), node_ids_visited (text array), created_at.

**document_session_links** — Many-to-many join between sessions and documents. Composite PK: session_id + document_id.

**eval_results** — Quality scores per assistant message. Fields: id, message_id (FK), document_id (FK), faithfulness_score, faithfulness_reason, answer_relevancy_score, contextual_precision_score, contextual_recall_score, hallucination_score, overall_pass (boolean), eval_model, triggered_by (online/nightly/ci), evaluated_at.

**eval_config** — Per-workspace quality thresholds. Fields: id, workspace_id (FK, unique), faithfulness_threshold (0.85), answer_relevancy_threshold (0.80), contextual_precision_threshold (0.75), contextual_recall_threshold (0.75), hallucination_threshold (0.15), multi_turn_enabled (boolean).

**audit_logs** — Records every user action. Fields: id, user_id (FK), action ("document.upload", "chat.query"), resource_type, resource_id, metadata (JSONB), timestamp.

**model_provider_configs** — LLM/embedding provider settings per workspace. Fields: id, workspace_id (FK), provider_type (llm/embedding/rerank), provider_name (bedrock/openai/anthropic/gemini/deepseek/grok), model_id, api_key, region, extra_config (JSONB), is_default (boolean), created_at.

---

## Every File Explained

### Root Files

`docker-compose.yml` — Defines all 5 Docker services (backend, celery-worker, postgres, redis, frontend), their ports, environment variables, health checks, and how they connect via a shared network.

`Makefile` — Shortcut commands: `make up` (start), `make down` (stop), `make logs` (view logs), `make reset` (clean slate restart), `make shell-backend` (open backend shell), `make shell-db` (open PostgreSQL shell).

`setup.sh` — Complete setup script: checks prerequisites (Docker, AWS CLI), verifies AWS credentials, creates S3 bucket, cleans up old containers, verifies .env file, builds and starts Docker containers, waits for health checks, seeds admin user.

`.env.example` — Template for the .env file. Lists all required environment variables with placeholder values.

`.env` — Actual configuration (not committed to git). Contains database URL, Redis URL, JWT secret, AWS credentials, S3 bucket name, CORS origins, rate limits.

`.gitignore` — Tells Git which files to NOT track: .env (secrets), node_modules (huge), __pycache__ (compiled Python).

`ARCHITECTURE.md` — High-level architecture documentation with diagrams.

`README.md` — Project readme with setup instructions.

---

### Backend — Core (`backend/app/core/`)

`config.py` — Reads the .env file using Pydantic BaseSettings. Every setting becomes an attribute: `settings.database_url`, `settings.s3_bucket`, `settings.secret_key`, etc. The `parse_cors_origins` validator handles both comma-separated strings and JSON arrays for CORS origins.

`database.py` — Creates the async SQLAlchemy engine (a connection pool to PostgreSQL) and session factory. The `Base` class is the parent for all database models — SQLAlchemy uses it to know "these Python classes represent database tables." The `get_db()` function is a FastAPI dependency — every API endpoint that needs the database declares `db = Depends(get_db)` and gets a session that auto-closes when the request is done.

`security.py` — JWT authentication layer. `create_access_token()` creates a token containing user_id, workspace_id, and role that expires in 30 minutes. `create_refresh_token()` creates a token that expires in 7 days. `get_current_user` is a FastAPI dependency that decodes the JWT from the Authorization header, fetches the user from DB, and raises 401 if invalid. `require_role("editor")` is a dependency factory that checks the user's role against a hierarchy (viewer < editor < admin) and raises 403 if insufficient.

`__init__.py` — Empty file that makes `core` a Python package.

---

### Backend — Models (`backend/app/models/`)

Each file defines one database table as a Python class.

`workspace.py` — The `workspaces` table. Root entity for multi-tenancy. Every other table links back here through workspace_id.

`user.py` — The `users` table. Defines the `UserRole` enum (admin/editor/viewer). Each user belongs to one workspace.

`knowledge_base.py` — The `knowledge_bases` table. The `settings` JSONB column stores RAG mode configuration (rag_mode, chunk_size, retrieval_mode, embedding_provider, etc.).

`document.py` — The `documents` table. Defines the `DocumentStatus` enum (uploading/processing/ready/failed). Tracks uploaded files with their S3 path and processing status.

`document_tree.py` — The `document_trees` table. One-to-one with documents (PageIndex mode only). Stores the hierarchical tree as JSONB plus auto-generated insights (summary, entities, tags, complexity score).

`document_chunk.py` — The `document_chunks` table. Many per document (Vector RAG only). Each chunk has text, positional metadata, optional parent reference (for parent-child strategy), and a 1024-dimension embedding vector. Falls back gracefully if pgvector isn't installed.

`chat_session.py` — The `chat_sessions` table. A conversation tied to one KB and one user.

`chat_message.py` — The `chat_messages` table. Stores role (user/assistant), content, citations (JSONB), reasoning trace (JSONB), and node_ids_visited (which tree nodes or chunks were used).

`document_session_link.py` — Join table linking sessions to documents. Composite primary key.

`eval_result.py` — The `eval_results` table. 5 metric scores per assistant message plus overall_pass boolean.

`eval_config.py` — The `eval_config` table. Per-workspace quality thresholds with defaults.

`audit_log.py` — The `audit_logs` table. Records every user action with flexible JSONB metadata.

`model_provider.py` — The `model_provider_configs` table. Stores LLM/embedding provider settings per workspace.

`wiki_page.py` — The `wiki_pages` table. LLM-maintained wiki pages with title (merge key), content (markdown), source document tracking, and cross-references.

`__init__.py` — Imports and exports all model classes so they can be used elsewhere with `from app.models import User, Document, ...`.

---

### Backend — Schemas (`backend/app/schemas/`)

Schemas define the shape of API request/response data using Pydantic. They validate incoming data and format outgoing data.

`auth.py` — `LoginResponse` (access_token + refresh_token), `RefreshRequest` (refresh_token), `RefreshResponse` (new access_token).

`chat.py` — `ChatSessionCreate` (needs kb_id), `ChatSessionOut` (full session info), `ChatMessageCreate` (needs content), `ChatMessageOut` (includes citations, reasoning_trace, node_ids_visited).

`documents.py` — `DocumentUploadResponse` (document_id, status, filename, kb_id), `DocumentOut` (full document info + optional chunk_count).

`knowledge_bases.py` — `KnowledgeBaseCreate` (name, description, settings), `KnowledgeBaseUpdate`, `KnowledgeBaseOut` (includes computed rag_mode from settings), `KnowledgeBaseDetail` (includes documents list).

`__init__.py` — Empty.

---

### Backend — API Routes (`backend/app/api/routes/`)

Each file defines a group of HTTP endpoints.

`auth.py` — Three endpoints:
- `POST /auth/login` — Takes email+password as form data, verifies with bcrypt, returns JWT access+refresh tokens.
- `POST /auth/refresh` — Takes refresh token, verifies it's valid and not expired, returns new access token.
- `POST /auth/logout` — Requires auth but does nothing (token remains valid until expiry).

`health.py` — Three health check endpoints:
- `GET /health` — Returns `{"status": "ok"}`. Used by Docker to check if the app is running.
- `GET /health/db` — Runs `SELECT 1` against PostgreSQL. Returns error if DB is down.
- `GET /health/redis` — Pings Redis. Returns error if Redis is down.

`documents.py` — Document management:
- `POST /documents/upload` — The upload endpoint. Reads file bytes, checks size (<50MB), validates MIME type + magic bytes (first few bytes of the file to verify it's really a PDF/DOCX), checks workspace isolation (KB must belong to user's workspace), uploads to S3 asynchronously, creates document record in DB, logs the action in audit_logs, dispatches the right Celery task based on rag_mode (tree building for PageIndex, chunking+embedding for Vector, wiki extraction for Wiki). Returns 202 Accepted.
- `GET /documents` — Lists documents in the workspace, optionally filtered by kb_id. Includes chunk counts for Vector RAG documents.
- `GET /documents/{id}` — Gets a single document, scoped to workspace.
- `GET /documents/{id}/file` — Streams the raw file bytes from S3 for PDF viewing or download.

`knowledge_bases.py` — KB management:
- `POST /knowledge-bases` — Creates a new KB with unique name check.
- `GET /knowledge-bases` — Lists all KBs in the workspace with document counts.
- `GET /knowledge-bases/{id}` — Gets KB detail with document list.
- `PATCH /knowledge-bases/{id}` — Updates name/description/settings. Requires editor+ role.
- `DELETE /knowledge-bases/{id}` — Cascade deletes everything: eval_results → messages → sessions → document links → trees → chunks → documents → KB → S3 files. Requires admin role.

`chat.py` — The main chat system:
- `POST /chat/sessions` — Creates a new session. Auto-deletes empty sessions (no messages) first.
- `GET /chat/sessions` — Lists sessions that have at least one message.
- `POST /chat/sessions/{id}/messages` — The main chat endpoint. Rate limits the user, stores the user message, auto-titles the session from the first message, loads conversation history (last 5 turns), checks rag_mode, then branches:
  - PageIndex: loads document trees → navigator LLM picks relevant nodes → answer LLM generates cited response
  - Vector RAG: embeds query → retriever finds similar chunks → answer LLM generates cited response
  - Wiki: loads wiki pages → navigator LLM picks relevant pages → answer LLM generates cited response
  After generating, stores the assistant message, triggers async evaluation via Celery, returns the response.
- `DELETE /chat/sessions/{id}` — Deletes a session.
- `GET /chat/sessions/{id}/messages` — Returns full message history.
- `WS /ws/chat/{session_id}` — WebSocket endpoint for streaming. Same RAG pipeline but streams tokens over WebSocket instead of returning all at once.

`eval.py` — Evaluation and analytics (admin only):
- `GET /eval/config` — Returns workspace eval thresholds.
- `PATCH /eval/config` — Updates thresholds.
- `GET /eval/results/{message_id}` — Returns eval scores for a specific message.
- `GET /eval/analytics/top-queries` — Most asked questions per KB.
- `GET /eval/analytics/confidence-distribution` — Score histogram in 5 buckets.
- `GET /eval/analytics/low-confidence` — Worst-scoring messages.
- `GET /eval/analytics/trend` — Daily average faithfulness scores.
- `GET /eval/analytics/heatmap` — Per-document quality averages.
- `GET /eval/analytics/distribution` — All 5 metric score arrays.
- `GET /eval/analytics/low-scores` — Messages below faithfulness threshold.

`insights.py` — Document insights:
- `GET /insights/{doc_id}` — Returns different data per rag_mode:
  - PageIndex: tree_json + executive_summary + key_entities + document_tags + complexity_score
  - Vector RAG: chunk list with embedding status, counts, page numbers
  - Wiki: wiki pages sourced from that document

`model_providers.py` — LLM/embedding provider management:
- `GET /model-providers` — Lists all configured providers.
- `POST /model-providers` — Creates a new provider config. Auto-unsets previous default of same type.
- `GET /model-providers/defaults` — Returns the default provider per type (llm/embedding/rerank).
- `PUT /model-providers/defaults` — Sets defaults.
- `PUT /model-providers/{id}` — Updates a provider config.
- `DELETE /model-providers/{id}` — Deletes a provider config.
- `POST /model-providers/{id}/test` — Makes a sample API call to verify credentials work.

`retrieval.py` — Hit-testing for Vector RAG:
- `POST /retrieval/test` — Runs retrieval without generating an answer. Returns ranked chunks with scores. Only works for vector-mode KBs.

`wiki_pages.py` — Wiki page access:
- `GET /knowledge-bases/{kb_id}/wiki-pages` — Lists all wiki pages (summary view).
- `GET /knowledge-bases/{kb_id}/wiki-pages/{page_id}` — Returns full page content.

`__init__.py` — Empty.


---

### Backend — Services (Business Logic)

#### PageIndex Engine (`services/pageindex/`)

`tree_builder.py` — Builds hierarchical trees from documents. Sends document text (up to 8000 chars) to the LLM with a system prompt asking for a JSON tree with nodes (node_id, title, page_start, page_end, depth, text, children). Parses the response, falls back to a single-node tree if parsing fails. Helper functions: `count_nodes` (counts all nodes), `max_depth` (deepest nesting level), `collect_node_ids` (lists all IDs).

`tree_navigator.py` — Query-time section selection. Takes the user's question and all document trees, builds a compact table of contents (with prefixed node IDs like `doc_id::node_id` to prevent collisions across documents), sends to the LLM asking it to select max 10 relevant nodes. Returns `NavigationResult` with selected_node_ids, rationale per node, and confidence score (0.0-1.0).

`answer_generator.py` — Generates cited answers. Takes selected node IDs, looks up their full text from the trees, builds a prompt with conversation history (last 5 turns) and section text. The LLM produces a markdown answer with `[citation:N]` markers inside `<answer>` tags and a structured JSON citations array inside `<citations>` tags. The parser extracts clean answer text + Citation objects. Also has `stream_answer` for token-by-token streaming.

`chunk_answer_generator.py` — Same as answer_generator but for Vector RAG. Takes `RetrievalResult` chunks instead of tree nodes. Reuses the same citation prompt and parsing logic. Enriches citations with chunk metadata (document_id, page_number).

`trace_logger.py` — Records the navigation path. Builds a `ReasoningTrace` from navigation results: ordered list of `NodeVisit` entries (node_id, title, rationale, depth) plus overall confidence. Stored in `chat_messages.reasoning_trace` for debugging and transparency.

`__init__.py` — Empty.

#### LLM Providers (`services/llm/`)

`provider.py` — Defines the interface (Protocol) that all LLM providers must implement: `complete(messages, system_prompt) → LLMResponse` and `stream(messages, system_prompt) → AsyncIterator[str]`. `LLMResponse` contains content, model name, input_tokens, output_tokens.

`factory.py` — `get_llm_provider(workspace_id, db)` queries the `model_provider_configs` table for the workspace's default LLM provider. If none configured, falls back to BedrockProvider (Claude Sonnet 4.5). Supports 6 providers: bedrock, openai, anthropic, deepseek, grok, gemini.

`bedrock.py` — AWS Bedrock provider using Claude Sonnet 4.5. Uses boto3 with SSO profile (dev) or IAM role (prod). Has retry logic: 3 retries with exponential backoff (wait 1s, 2s, 4s) for throttling errors. Runs synchronous boto3 calls in `run_in_executor` to avoid blocking the async event loop. Supports both complete (full response) and streaming (token by token).

`openai_compat.py` — Generic OpenAI-compatible provider. Works with OpenAI (api.openai.com), DeepSeek (api.deepseek.com/v1), Grok (api.x.ai/v1), and Anthropic (api.anthropic.com/v1) — all use the same chat completions API format with different server URLs. Uses the async OpenAI Python SDK.

`gemini_provider.py` — Google Gemini via the google-genai SDK. Converts OpenAI-style messages to Gemini Content objects. Runs synchronous SDK calls in executor. Streaming uses a queue-based producer/consumer pattern: a background thread produces tokens, the async code consumes them.

`openai_provider.py` — Stub implementation (not yet wired up). Raises NotImplementedError.

`anthropic_provider.py` — Stub implementation (not yet wired up). Raises NotImplementedError.

`__init__.py` — Empty.

#### Document Processing (`services/document/`)

`extractor.py` — Converts document files into plain text. PDF: uses pdfplumber (extracts text page by page, preserves tables as pipe-delimited text, adds page breaks). DOCX: uses python-docx (preserves heading hierarchy as markdown markers like `## Heading 2`). TXT/MD: plain file read. If the file is in S3 (not on local disk), downloads it first to a temp file.

`storage.py` — S3 file storage. `store_async()` uploads file bytes to S3 using aiobotocore (async AWS SDK), returns the S3 key. `store()` is the sync version for Celery workers. `delete()` removes a file from S3. Files are stored under `workspaces/{workspace_id}/{random-uuid}.{ext}`.

`__init__.py` — Empty.

#### Chunking (`services/chunking/`)

`factory.py` — Creates chunkers by strategy name: "recursive" or "parent_child". Configurable chunk_size and chunk_overlap.

`recursive_splitter.py` — Splits text using a hierarchy of separators: double newline → newline → sentence (". ") → word (" ") → character. Tries the first separator; if chunks are still too big, falls back to the next. Maintains overlap between consecutive chunks (default 200 chars) so context isn't lost at boundaries. Returns chunks with positional metadata (char_start, char_end, page_number, chunk_index).

`parent_child_splitter.py` — Two-pass splitter. Pass 1: splits into big parent chunks (default 2000 chars) on paragraph boundaries with no overlap. Pass 2: splits each parent into small child chunks (default 300 chars) with 50 char overlap. Parents get `parent_chunk_index=None`, children get `parent_chunk_index` pointing to their parent's index. At indexing time, only children get embeddings (saves money). At query time, when a child matches, the system can follow the parent reference to get the full paragraph context.

`__init__.py` — Empty.

#### Embedding (`services/embedding/`)

`provider.py` — Defines the interface: `embed_texts(texts) → EmbeddingResult` (batch), `embed_query(text) → list[float]` (single), `get_dimensions() → int`.

`factory.py` — Creates Bedrock or OpenAI embedding providers based on provider_name and model_id.

`bedrock_embedding.py` — Amazon Titan Embed Text v2 (1024 dimensions). Converts text to 1024 numbers that represent the meaning. Runs synchronous boto3 calls in `asyncio.to_thread` to avoid blocking.

`openai_embedding.py` — OpenAI text-embedding-3-small (1024 dimensions). Uses the async OpenAI SDK. Same 1024 dimensions as Bedrock for compatibility.

`__init__.py` — Empty.

#### Indexing (`services/indexing/`)

`vector_indexer.py` — Takes chunks from a splitter, embeds them in batches of 50 (to avoid API limits), and stores them in the `document_chunks` table. For parent-child strategy: stores parents first WITHOUT embeddings (saves money), then embeds and stores children WITH embeddings + parent_chunk_id foreign key. For recursive strategy: embeds and stores all chunks equally.

`fulltext_indexer.py` — Stores chunks WITHOUT embeddings. Full-text search is handled by PostgreSQL's built-in GIN index on tsvector — no separate indexing step needed.

`__init__.py` — Empty.

#### Retrieval (`services/retrieval/`)

`retriever.py` — Defines the `RetrievalResult` dataclass: chunk_id, document_id, doc_filename, text, score, page_number, chunk_index.

`factory.py` — Creates the right retriever based on KB settings: "vector" → VectorRetriever, "fulltext" → FullTextRetriever, "hybrid" → HybridRetriever.

`vector_retriever.py` — Cosine similarity search via pgvector. Embeds the user's query into a vector, then runs a SQL query that computes `1 - (embedding <=> query_vector)` as the similarity score for every chunk. The `<=>` operator is pgvector's cosine distance. Returns top-k chunks above optional score threshold.

`fulltext_retriever.py` — PostgreSQL full-text search. Uses `to_tsvector('english', text)` to tokenize chunk text (removes stop words, stems words), `plainto_tsquery('english', query)` to tokenize the query, `@@` operator to match, and `ts_rank` to score (based on term frequency, word proximity, and document length).

`hybrid_retriever.py` — Runs vector and full-text retrieval in parallel using `asyncio.gather`, then merges results using Reciprocal Rank Fusion (RRF). Formula: `RRF_score = (semantic_weight / (vector_rank + 60)) + (keyword_weight / (fulltext_rank + 60))`. Default weights: 0.7 vector / 0.3 keyword. K=60 is a standard constant that smooths rank differences. Chunks found by both methods get higher scores.

`__init__.py` — Empty.

#### Evaluation (`services/eval/`)

`metrics.py` — Defines default thresholds (faithfulness ≥0.85, answer_relevancy ≥0.80, contextual_precision ≥0.75, contextual_recall ≥0.75, hallucination ≤0.15). Builds 5 DeepEval metric instances using the Bedrock judge model.

`bedrock_judge.py` — Creates a singleton `AmazonBedrockModel` instance for DeepEval evaluation. Always uses Claude Sonnet 4.5 on Bedrock as the judge, regardless of what the workspace uses for chat. Falls back gracefully if DeepEval isn't installed or Python < 3.10.

`test_case.py` — `build_test_case(message_id, db)` constructs a DeepEval `LLMTestCase` from a stored assistant message. Fetches: the preceding user question (input), the assistant's answer (actual_output), and the source text that was used (retrieval_context — looked up from tree nodes or chunks using node_ids_visited).

`quality_gate.py` — After evaluation, checks if faithfulness < threshold OR hallucination > threshold. If either is breached, appends a disclaimer to the stored message: "⚠️ This response may not fully reflect the source documents." The user sees this on their next page load.

`__init__.py` — Empty.

#### Wiki (`services/wiki/`)

`wiki_builder.py` — Two LLM operations:
1. `extract_pages()` — Sends document text (up to 10,000 chars) to the LLM with a prompt asking for 3-15 wiki page structures (title, page_type, summary, content, related_titles). Returns parsed JSON.
2. `merge_page_content()` — When a topic already has a wiki page, sends old content + new content to the LLM asking it to merge them. The LLM preserves existing info, integrates new facts, and flags contradictions with blockquote markers.

`wiki_navigator.py` — Query-time page selection. Builds a compact table of contents of all wiki pages (id, type, title, summary), sends to the LLM asking which 1-8 pages are relevant. Validates returned page IDs against actual pages to prevent hallucinated UUIDs.

`wiki_answer_generator.py` — Generates cited answers from selected wiki pages. Reuses the same citation prompt and parsing as PageIndex. Citations link to the originating document via source_doc_ids.

`__init__.py` — Empty.

#### KB Service (`services/kb_service.py`)

Helper functions: `get_kb_or_403` (fetches KB, verifies workspace ownership), `assert_unique_name` (raises 409 if duplicate name), `get_document_count` (COUNT query), `assert_no_active_sessions` (prevents deletion if sessions exist).

`services/__init__.py` — Empty.

---

### Backend — Workers (Background Tasks)

`celery_app.py` — Creates the Celery application. Configures Redis as broker/backend, JSON serialization, UTC timezone. Routes tasks to queues: document processing → "default" queue, evaluation → "eval_queue" (separate so eval doesn't block processing).

`tree_tasks.py` — `build_document_tree` Celery task (PageIndex mode). Extracts text from document → sends to LLM for tree + insights generation in a single combined call → parses response → stores tree in document_trees table → marks document status as "ready" → pushes WebSocket event via Redis pub/sub. 3 retries with exponential backoff (10s, 20s, 40s). On exhaustion: marks document as "failed".

`index_tasks.py` — `index_document` Celery task (Vector RAG mode). Extracts text → creates chunker from KB settings → chunks the document → creates embedding provider → indexes chunks (vector or fulltext based on index_method) → marks document "ready" → pushes WebSocket event. Same retry policy.

`wiki_tasks.py` — `build_wiki_pages` Celery task (Wiki mode). Extracts text → LLM extracts 3-15 wiki page structures → for each page: if title already exists in KB, merge new content into existing page (another LLM call); if new title, create new page (up to 100 per KB cap) → marks document "ready". Same retry policy.

`eval_tasks.py` — `evaluate_response_async` Celery task. Runs after every chat message. Builds LLMTestCase (user question + AI answer + source text) → loads workspace thresholds → runs 5 DeepEval metrics using judge LLM (or sample scores if Bedrock unavailable) → stores scores in eval_results → runs quality gate (may append disclaimer) → optionally runs multi-turn evaluation if enabled. 2 retries, fails open (never blocks the user).

`maintenance_tasks.py` — Celery Beat scheduled tasks:
- `run_nightly_eval` (2 AM UTC): Re-evaluates all assistant messages from past 24 hours. Compares today's average scores against 7-day rolling baseline. Logs warning if any metric drops >5%.
- `cleanup_orphaned_files` (3 AM UTC): Lists all S3 objects, compares against document records in DB, deletes S3 files older than 30 days that have no matching document record.

`__init__.py` — Empty.

---

### Backend — Database Migrations (`backend/alembic/`)

`alembic.ini` — Alembic configuration file. Points to the migration scripts directory.

`env.py` — Connects Alembic to the database. Imports all models so Alembic can detect table changes. Runs migrations either offline (generates SQL) or online (executes against DB).

`script.py.mako` — Template for generating new migration files.

`versions/0001_initial_schema.py` — Creates all 11 original tables: workspaces, users, knowledge_bases, documents, document_trees, chat_sessions, chat_messages, document_session_links, eval_results, eval_config, audit_logs. Also creates indexes and the pgcrypto extension.

`versions/0003_add_multi_turn_enabled_to_eval_config.py` — Adds `multi_turn_enabled` boolean column to eval_config.

`versions/0004_make_workspace_id_nullable.py` — Makes workspace_id nullable on the users table (needed for the seed script which creates user before workspace).

`versions/99cb697df279_add_hashed_password_to_users.py` — Adds `hashed_password` column to users table.

`versions/a1b2c3d4e5f6_add_vector_rag.py` — Enables pgvector extension, creates document_chunks table with vector(1536) column, creates GIN index for full-text search, creates model_provider_configs table.

`versions/b2c3d4e5f6a7_fix_embedding_dimension_1024.py` — Changes embedding column from 1536 to 1024 dimensions (to match Titan Embed v2).

`versions/c1d2e3f4g5h6_add_wiki_pages.py` — Creates wiki_pages table with indexes.

---

### Backend — Tests (`backend/tests/`)

`conftest.py` — Shared test setup. Sets fake environment variables, creates `MockLLMProvider` (returns fixed responses without calling Bedrock), factory functions for test users/workspaces, mock database session, and async HTTP test client.

`tests/eval/conftest.py` — Empty (eval tests don't need extra fixtures).

`tests/eval/golden/hr.jsonl` — 50 pre-written HR policy Q&A pairs for regression testing. Each line is a JSON object with input (question), actual_output (known-good answer), and retrieval_context (source text).

`tests/eval/golden/legal.jsonl` — 50 pre-written legal contract Q&A pairs.

`tests/eval/golden/financial.jsonl` — 50 pre-written financial report Q&A pairs.

`tests/eval/test_rag_quality.py` — CI regression test suite. Two test classes:
1. `TestGoldenDatasetIntegrity` — Validates golden datasets have correct structure (min 50 cases, required fields, non-empty values). Runs without Bedrock.
2. `TestRAGQuality` — Runs DeepEval faithfulness (≥0.85) and relevancy (≥0.80) on all 150 golden cases. Requires Bedrock access, skipped by default.

`tests/test_logging.py` — Property-based test using Hypothesis. Generates random URL paths and HTTP methods, sends requests, verifies every log entry is valid JSON with a correlation_id that matches the response header.

---

### Backend — Other Files

`backend/app/main.py` — FastAPI entry point. Sets up structured JSON logging (every log line is JSON with timestamp, level, correlation_id). Adds CorrelationIdMiddleware (assigns unique ID to every request for log tracing). Adds CORS middleware. Registers all route modules. Sets up global exception handler.

`backend/Dockerfile` — Docker image for the backend. Uses Python 3.11-slim, installs system dependencies (gcc, libpq-dev for PostgreSQL), installs Python packages from requirements.txt.

`backend/requirements.txt` — Python production dependencies: fastapi, sqlalchemy, pydantic, boto3, celery, redis, pdfplumber, python-docx, etc.

`backend/requirements-dev.txt` — Dev dependencies: pytest, hypothesis, httpx, etc.

`backend/pytest.ini` — Pytest configuration.

`backend/seed_admin.py` — Script to create the first admin user and workspace. Creates user (admin@documind.ai / Admin123!), creates "Default Workspace", links them together.

`backend/check_eval_data.py` — Utility to inspect eval data in the database.

`backend/check_eval_data.sql` — SQL queries for eval data inspection.

`backend/start_eval_worker.sh` — Shell script to start the eval Celery worker.

`backend/restart_eval_worker_and_populate.sh` — Restarts eval worker and seeds data.


---

### Frontend — Entry Points

`frontend/index.html` — The single HTML page. Has a `<div id="root">` that React fills with content.

`frontend/src/main.tsx` — React entry point. Creates the React app and mounts it to the HTML page inside BrowserRouter (for URL routing) and StrictMode (for development warnings).

`frontend/src/App.tsx` — Root component. Defines the top navigation bar (Knowledge Bases, Chat, Analytics, RAG Guide, Settings, Logout). `RequireAuth` wrapper checks localStorage for access_token — if missing, redirects to /login. Routes: / (Landing), /login, /knowledge-bases, /chat, /analytics, /guide, /settings, /documents/:docId.

`frontend/src/index.css` — Global styles. CSS variables for brand colors (--dm-primary), Tailwind imports, font settings.

---

### Frontend — Types (`frontend/src/types/`)

`index.ts` — All TypeScript interfaces defining data shapes: ChatMessage (id, role, content, citations), ChatSession (id, kb_id, title), Citation (document_id, filename, page_number, excerpt), Document (id, filename, status, chunk_count), KBSettings (rag_mode, chunk_size, retrieval_mode, etc.), KnowledgeBase, WikiPage, WikiPageDetail, ModelProviderConfig, UploadItem, EvalResult, EvalConfig.

---

### Frontend — API Layer (`frontend/src/api/`)

`client.ts` — Creates an Axios HTTP client configured with base URL /api/v1. Request interceptor attaches JWT token from localStorage to every request. Response interceptor catches 401 errors and automatically refreshes the token — queues concurrent requests during refresh, retries them with the new token. If refresh also fails, clears tokens and redirects to /login.

`chat.ts` — API functions: createSession(kb_id), getSessions(), deleteSession(id), getMessages(session_id), sendMessage(session_id, content) — sendMessage uses raw fetch instead of Axios for SSE streaming support.

`documents.ts` — API functions: uploadDocument(file, kb_id, onProgress) — multipart upload with progress callback, getDocuments(kb_id?), getDocument(doc_id), createKnowledgeBase(name, desc, settings), getKnowledgeBases(), deleteKnowledgeBase(kb_id), updateKnowledgeBase(kb_id, updates).

`eval.ts` — API functions: getEvalResults(message_id), getEvalConfig(), updateEvalConfig(config).

`insights.ts` — fetchDocumentInsights(docId) — returns typed response for PageIndex (tree + summary) or Vector (chunks + stats) or Wiki (wiki pages).

`wiki.ts` — getWikiPages(kbId), getWikiPage(kbId, pageId).

---

### Frontend — State Management (`frontend/src/stores/`)

`chatStore.ts` — Zustand store for chat state: sessions (list of all sessions), activeSessionId (which session is open), messages (keyed by session ID), isStreaming (whether AI is generating), streamingContent (partial response). Actions: setSessions, setActiveSession, setMessages, addMessage, updateStreamingContent, setStreaming, clearStreaming.

`documentStore.ts` — Zustand store for documents: documents (list), knowledgeBases (list), activeKbId, uploadQueue (files being uploaded with progress). Actions: setDocuments, updateDocument, setKnowledgeBases, setActiveKb, addToUploadQueue, updateUploadProgress, removeFromUploadQueue.

`uiStore.ts` — Zustand store for general UI state: leftPanelOpen, rightPanelOpen, activeKbId, pdfViewerPage, pdfViewerDocId, pdfViewerHighlight, createKbModalOpen. Toggle and setter actions for each.

---

### Frontend — Hooks (`frontend/src/hooks/`)

`useChat.ts` — Custom hook combining chatStore + API calls. Provides: loadSessions(), createSession(kb_id), sendMessage(content) — creates optimistic user message, calls API, adds assistant response, loadMessages(session_id), setActiveSession(id) — with lazy message loading, deleteSession(id). Returns current state (sessions, messages, isStreaming, streamingContent).

`useDocuments.ts` — Custom hook combining documentStore + API calls. Provides: loadKnowledgeBases(), loadDocuments(kb_id?), uploadFile(file, kb_id) — adds to queue, uploads with progress, starts polling, deleteKb(kb_id), createKb(name, desc, settings), updateKb(kb_id, name, desc), pollDocumentStatus(doc_id) — checks every 3 seconds until ready/failed.

`useEvalResults.ts` — Fetches eval results for a message ID. Returns evalResult, isLoading, error. Auto-fetches when message_id changes.

`useStream.ts` — Wraps browser's EventSource API for Server-Sent Events. Manages connection lifecycle, provides isConnected state and close() function.

---

### Frontend — Pages (`frontend/src/pages/`)

`Login.tsx` — Email/password form. Posts credentials to /auth/login as URL-encoded form data, stores JWT tokens in localStorage, redirects to /knowledge-bases on success. Shows error message on invalid credentials.

`Landing.tsx` — Marketing landing page for unauthenticated users. Hero section with chat preview mockup, provider logos strip (Bedrock, OpenAI, Anthropic, Gemini, DeepSeek, Grok), 3 RAG mode cards with descriptions, features grid (9 features), how-it-works steps, testimonials, CTA section, footer.

`KnowledgeBases.tsx` — Main KB management page. Shows KB cards in a grid with color-coded RAG mode badges (blue=PageIndex, green=Vector, purple=Wiki). Click a card to see detail view with tabs:
- Documents tab: drag-drop upload zone, progress tracker, document table with status/chunks/actions
- Wiki Pages tab (Wiki mode only): WikiPageExplorer component
- Settings tab: shows all KB configuration
Also has: multi-step creation wizard (basic info → RAG mode selection → vector-specific config → review), edit modal, delete confirmation, hit testing panel for Vector KBs.

`Chat.tsx` — Three-panel chat interface. Left sidebar: KB selector (click to start new session) + session list (click to switch, trash icon to delete). Center: message list with MessageBubble components, streaming indicator (bouncing dots), input textarea with send button. Citations in messages are clickable — navigate to document viewer with page number and highlight text.

`Library.tsx` — Simple document grid grouped by KB. Each DocumentCard shows filename, type icon, size, status badge. Click navigates to document viewer.

`Analytics.tsx` — Admin dashboard. EvalThresholds form (5 sliders + multi-turn toggle + save button). QualityMonitor component (low-faithfulness messages table). ChatAnalytics section: top queries table with bar indicators, confidence distribution SVG bar chart (5 colored bars), low-confidence queries list with percentage badges.

`DocumentViewerPage.tsx` — Split-panel document viewer. Left (60%): PDF viewer for PDFs, "preview not available" for other types. Right (40%): tabbed panel — Structure tab (tree explorer for PageIndex, expandable chunk list for Vector, wiki pages for Wiki), Insights tab (summary/entities/stats for PageIndex, embedding coverage stats for Vector, info message for Wiki).

`Settings.tsx` — Model provider management. Table showing all configured providers (type, provider, model, default badge). Add Provider form with dropdowns for type (LLM/Embedding), provider (Bedrock/OpenAI/etc.), model (pre-populated list), API key or region. Test button makes sample API call. Delete button removes config.

`RAGGuide.tsx` — Educational page. Collapsible sections for each RAG mode: how it works (with analogy), pros & cons, when to use (with concrete examples). Comparison table (ingest cost, query cost, cross-doc synthesis, etc.). Decision guide flowchart. Note that RAG mode can't be changed after KB creation.

---

### Frontend — Components (`frontend/src/components/`)

`chat/MessageBubble` — Renders one chat message. User messages: blue bubble on the right. Assistant messages: white bubble on the left with markdown rendering, citation badges (clickable, show document name + page number).

`chat/StreamingIndicator` — Three bouncing dots animation shown while the AI is generating a response.

`upload/DropZone` — Dashed-border area for drag-and-drop file upload. Validates file types (PDF/DOCX/TXT/MD). Also has a "browse" link for file picker.

`upload/ProgressTracker` — Shows upload progress bars and processing status for each file in the upload queue.

`upload/DocumentCard` — Card showing document name, file type icon, size, and status badge (Ready/Processing/Failed).

`viewer/PDFViewer` — Renders PDF files using react-pdf. Supports page navigation and text highlighting.

`insights/DocumentSummary` — Shows PageIndex insights: executive summary, key entities (people, organizations, dates, amounts), document tags, complexity score.

`insights/TreeExplorer` — Interactive tree visualization for PageIndex. Expandable/collapsible nodes showing title, page range, and text excerpt.

`insights/QualityMonitor` — Table of messages with low faithfulness scores. Shows content preview, score badge, and timestamp.

`wiki/WikiPageExplorer` — Lists wiki pages for a KB. Click a page to see full markdown content, related pages, source documents, and metadata.

`library/` — Library view components.

---

### Frontend — Config Files

`frontend/package.json` — Lists all JavaScript dependencies and scripts. Key deps: react, react-router-dom, axios, zustand, lucide-react, tailwindcss, react-pdf, react-markdown.

`frontend/vite.config.ts` — Vite configuration. Sets up proxy rules: /api/* → backend:8010, /auth/* → backend:8010 (with path rewrite), /health/* → backend:8010, /ws/* → backend:8010 (WebSocket). This means the frontend and backend appear to be on the same domain from the browser's perspective.

`frontend/tailwind.config.ts` — Tailwind CSS configuration with custom colors and fonts.

`frontend/tsconfig.json` — TypeScript configuration. Strict mode enabled.

`frontend/postcss.config.js` — PostCSS config for Tailwind processing.

`frontend/components.json` — shadcn/ui component configuration.

`frontend/Dockerfile` — Docker image using Node 20 Alpine. Installs npm dependencies, runs Vite dev server.

`frontend/.dockerignore` — Excludes node_modules from Docker build context.

---

## Known Flaws

1. **Undefined variable `_CLAUDE_MODEL`** in tree_tasks.py — will crash on the else branch when updating an existing tree.

2. **Wiki page title race condition** — no database unique constraint. Two simultaneous uploads can create duplicate pages.

3. **API keys stored in plain text** — model_provider.api_key is unencrypted in PostgreSQL.

4. **In-memory rate limiter** — doesn't work with multiple FastAPI workers. Should use Redis.

5. **Hardcoded `IS_ADMIN = True`** in frontend — every user sees admin UI.

6. **Logout doesn't invalidate tokens** — JWT remains valid until expiry.

7. **N+1 queries** in list_sessions and list_knowledge_bases — separate DB query per item instead of one batch query.

8. **PageIndex doesn't scale** past ~100 documents — navigator prompt gets too large.

9. **New database engine per Celery task** — expensive connection setup every time.

10. **No cascade deletes** on most foreign keys — manual deletion order required.

11. **`datetime.utcnow` deprecated** in Python 3.12+.

12. **No query rewriting** for Vector RAG multi-turn conversations — follow-up questions fail.

13. **`chunk_metadata` always empty** — JSONB column exists but never populated.

14. **No markdown-aware chunking** — headings can be separated from their content.

15. **Duplicate RAG branching logic** — same if/elif/else in both HTTP and WebSocket handlers.

16. **Circular import workarounds** — late imports inside functions throughout the codebase.
