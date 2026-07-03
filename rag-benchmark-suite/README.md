# DocuMind RAG Benchmark Suite

A standalone interface — its own backend, frontend, and database, on its own ports — that
implements the methodology in [`../docs/rag-benchmark-methodology.md`](../docs/rag-benchmark-methodology.md):
drive every `rag_mode` DocuMind supports through an identical dataset and question set, and
report comparable quality + operational metrics per mode.

It does **not** duplicate any RAG or eval logic. It drives the real DocuMind app through its
existing public API (create KB → upload documents → wait for ingestion → chat → poll DeepEval
results), the same way the DocuMind frontend does, then aggregates what comes back.

## Why a separate service

This runs independently of the DocuMind app (own ports, own Postgres) so that benchmarking
traffic — creating throwaway KBs, sending test queries, polling eval endpoints — never touches
the product's own frontend/routes, and so it can be pointed at any DocuMind environment
(local, staging) without being deployed alongside it.

| Component | Port | vs. DocuMind |
|---|---|---|
| `benchmark-web` (Vite/React) | 5190 | separate from DocuMind frontend (5180) |
| `benchmark-api` (FastAPI) | 8020 | separate from DocuMind backend (8010) |
| `benchmark-postgres` | 5441 | separate from DocuMind Postgres (5440) |

## Prerequisites

- The main DocuMind stack already running (`make up` from the repo root) with at least one
  admin user, and Bedrock/AWS credentials configured there — this suite doesn't need AWS
  credentials itself, only DocuMind does.
- Docker + Docker Compose.

## Setup

```bash
cd rag-benchmark-suite
cp .env.example .env
# edit .env: BENCHMARK_DOCUMIND_ADMIN_EMAIL / BENCHMARK_DOCUMIND_ADMIN_PASSWORD
# and BENCHMARK_DATASET_HOST_PATH -> a folder of PDFs/DOCX/TXT/MD to benchmark

docker compose up --build
```

- UI: http://localhost:5190
- API docs: http://localhost:8020/docs

## Datasource types

Five source types, all resolved by `api/app/dataset.py` into a flat list of local files before a
run starts — every mode gets the identical file set. None of them take a credential typed into
the UI; everything comes from this service's own environment (`.env`), per Minfy's data-handling
rules.

| Source type | `dataset_source_ref` format | Credentials (in `.env`) |
|---|---|---|
| `folder_path` | `/data/my-dataset` (mounted volume) | none |
| `s3` | `s3://bucket/prefix` | ambient AWS credential chain |
| `confluence` | `SPACEKEY` or `SPACEKEY:PAGEID` | `BENCHMARK_CONFLUENCE_BASE_URL` / `_EMAIL` / `_API_TOKEN` (Atlassian API token) |
| `gdrive` | a Drive folder ID | `BENCHMARK_GDRIVE_SERVICE_ACCOUNT_JSON` (service account key, share the folder with it) |
| `sharepoint` | `hostname\|/sites/site-name\|folder/path` | `BENCHMARK_AZURE_TENANT_ID` / `_CLIENT_ID` / `_CLIENT_SECRET` (Graph app-only, `Sites.Read.All`) |

Confluence pages are pulled via the REST API and flattened to plain text (HTML tags stripped —
good enough for RAG ingestion, not a faithful export). Google Docs are exported as plain text;
other Drive files download as-is if their extension is pdf/docx/txt/md. SharePoint/OneDrive files
are walked recursively via Microsoft Graph path-based addressing and downloaded as-is.

These three were implemented against the documented Confluence Cloud REST API, Google Drive API
v3, and Microsoft Graph API, but not exercised against a real tenant in this environment (no
credentials available here) — run one small smoke test per connector before relying on it for
a real benchmark, and expect to iterate on auth/permission edge cases the first time.

## Using it

1. **New Run** — name the run, pick a source type and point it at the dataset (see table above —
   never paste keys into the form itself), pick which RAG modes to compare, and write a fixed set
   of test questions (with optional expected answers).
   - **Generate draft questions** (optional): once a dataset location is filled in, click
     "Generate" in the Test Questions card to have DocuMind itself propose a starter set (see
     "Question generation" below). Every draft lands in the editable question list — review,
     edit, or delete before submitting the run.
2. Submitting kicks off the orchestrator in the background: for each selected mode it creates a
   fresh KB in DocuMind with that `rag_mode` (and `retrieval_mode` for vector's 3 sub-variants),
   uploads the same documents, waits for async ingestion, opens a chat session, asks every
   question, and polls DocuMind's own `/eval/results/{message_id}` for the 5 DeepEval scores.
3. **Run detail** page auto-refreshes while the run is in progress, showing a metrics table
   (faithfulness, answer relevancy, contextual precision/recall, hallucination, pass rate,
   ingestion time, storage footprint, unanswerable-question handling, citation precision/recall,
   p50/p95 latency) side by side per mode, plus every question/answer pair.
   - Mark a question "unanswerable" to test whether a mode correctly refuses instead of
     fabricating an answer — scored using DocuMind's own hallucination score as the proxy.
   - Add "expected source document(s)" to a question to get citation precision/recall against
     DocuMind's own citations — only meaningful for `pageindex`/`vector` today. `wiki`, `graph`,
     and `openkb` show "N/A" here because their citation `doc_name` is a page title / entity
     name, not a real source filename (see "Datasource types" above and the methodology doc).
4. **Download raw JSON** on the run detail page exports the same shape as
   `../docs/rag-benchmark-results.template.json`, so results can be archived or diffed across runs.

## Question generation

`POST /api/v1/question-drafts` (wired to the "Generate" button on the New Run page) drafts a
starter question set without this suite needing its own LLM/AWS credentials. It reuses
DocuMind's own chat pipeline instead of duplicating any RAG/LLM logic here, consistent with this
suite's core design principle:

1. Resolves the same dataset a real run would use (`api/app/dataset.py`).
2. Creates a throwaway **pageindex** KB in DocuMind (named `bench-qgen-<token>`) and uploads
   every resolved file.
3. Waits for ingestion (own shorter timeout — `BENCHMARK_QUESTION_GEN_INGESTION_TIMEOUT_SECONDS`,
   default 300s — since this is a synchronous, user-facing call, not a background run).
4. Sends one chat message instructing the model to propose a JSON array of questions covering a
   fact / multi-document / unanswerable mix, referencing only the real uploaded filenames.
5. Parses the JSON out of the response and deletes the scratch KB (best-effort cleanup either way).

**Known limitations of this approach:**
- The prompt goes through DocuMind's normal pageindex chat/answer-generation pipeline (built for
  answering user questions, not meta-tasks like "propose test questions") — the underlying model
  usually follows the JSON-only instruction, but formatting drift is possible. If parsing fails,
  the API returns a clear 502 error explaining that and showing the start of the raw response;
  just retry or lower the requested count.
- Each click ingests the dataset once and makes one DocuMind chat call — the normal ingestion +
  LLM cost of doing that, on top of whatever the real benchmark run will separately cost.
- Drafts are a starting point, not a validated question set — read every one before running a
  real benchmark against it, especially expected answers and the unanswerable questions.

## Known limitations / follow-ups

- DeepEval scoring depends on DocuMind having live Bedrock access; if `deepeval`/Bedrock aren't
  configured there, DocuMind's eval pipeline falls back to sample/randomised scores (see
  `backend/app/services/eval/bedrock_judge.py` / `eval_tasks.py::_sample_scores`) — fine for
  UI development, not for a real benchmark.
- `wiki`, `graph`, and `openkb` retrieval-context resolution was only just added to
  `backend/app/services/eval/test_case.py` in this same change — re-run a small smoke test after
  upgrading an existing DocuMind deployment to confirm those three modes score correctly.
- Confluence/Google Drive/SharePoint connectors are implemented against the documented APIs but
  untested against a real tenant — see "Datasource types" above.
- Citation precision/recall is only computed for `pageindex`/`vector` — `wiki`/`graph`/`openkb`
  need their answer generators changed to resolve `doc_name` through `source_doc_ids` to a real
  filename before this metric means anything for them (see methodology doc §5.1).
- Question generation (see above) can occasionally return unparseable output since it repurposes
  DocuMind's answer-generation pipeline rather than a dedicated completion endpoint — treat
  drafts as a review-before-you-run starting point, not guaranteed-valid output.
- This suite creates real KBs in the target DocuMind workspace (named `bench-<token>-<mode>`, or
  `bench-qgen-<token>` for question generation — the latter are deleted automatically after each
  generation call). Delete leftover run KBs from DocuMind's Knowledge Bases page once you're
  done, or extend this suite with a cleanup endpoint that calls
  `DELETE /knowledge-bases/{id}` for a completed run.
- No auth on this suite's own UI/API — it's an internal tool. Put it behind your VPN/reverse
  proxy before exposing it beyond localhost.
