# DocuMind RAG Benchmark Methodology

Status: draft methodology (design-only, not yet executed)
Owner: Madhu, Minfy Technologies
Last updated: 2026-07-01

## 1. Goal

Given one dataset (a folder of documents, or a datasource connection), ingest it into DocuMind under every RAG mode the platform supports, then produce a comparable set of quality and operational metrics per mode so the best mode can be chosen per use case.

## 2. RAG modes covered

DocuMind selects a RAG path per Knowledge Base via `KnowledgeBase.settings["rag_mode"]` (default `"pageindex"`). Five modes exist in the codebase today:

| rag_mode | Ingestion worker | Query path | What it does |
|---|---|---|---|
| `pageindex` | `tree_tasks.build_document_tree` | `tree_navigator` → `answer_generator` | Vectorless: LLM builds a hierarchical JSON tree per document; queries select up to 10 tree nodes by reasoning over the table of contents |
| `vector` | `index_tasks.index_document` | `RetrieverFactory` → `vector_retriever` / `fulltext_retriever` / `hybrid_retriever` | Classic chunk + embed + similarity search (Bedrock or OpenAI embeddings); `retrieval_mode` sub-setting picks vector / fulltext / hybrid |
| `wiki` | `wiki_tasks.build_wiki_pages` | `wiki_navigator` → `wiki_answer_generator` | LLM maintains a living set of wiki pages per KB, updated as documents are added |
| `graph` | `graph_tasks.build_document_graph` | `graph_navigator` → `graph_answer_generator` (Neo4j) | Entity/relationship extraction into a graph; queries traverse the graph |
| `openkb` | `openkb_tasks.build_openkb_pages` | `openkb.navigator` → `openkb.answer_generator` | Compiled knowledge base of summary / concept / entity pages |

Note: `vector` mode has 3 retrieval sub-strategies (`retrieval_mode`: `vector`, `fulltext`, `hybrid`, default `vector`, weight configurable via `hybrid_semantic_weight`). Treat these as 3 additional variants if a finer-grained comparison is wanted — see §6.

## 3. Dataset input

Two supported ways to point the benchmark at documents, matching how DocuMind already ingests:

1. **Folder path** — a local/mounted directory of source files (PDF, DOCX, TXT). Same folder is re-used for every mode so the comparison is apples-to-apples.
2. **Datasource connection** — an existing connector/location already known to the app (e.g. an S3 prefix wired through the app's document upload flow). No credentials should ever be pasted into chat or committed to this repo — reference the connection by name/alias only, per Minfy's DPDP-aligned data handling rules.

Before ingesting, screen the dataset for PII/confidential markings. If any document is marked Confidential/Restricted or contains personal data not needed for the benchmark, redact or exclude it first — the benchmark output (chat transcripts, retrieved snippets) will be stored in `eval_results` and in the report below, so anything ingested can resurface there.

## 4. Benchmark design

1. **One Knowledge Base per mode.** Create 5 KBs (plus any `vector` sub-variants from §6) in the same workspace, each with `settings.rag_mode` set accordingly, all other settings held constant (`top_k`, embedding provider, chunk size) unless the setting is mode-specific.
2. **Same document set into every KB.** Upload the identical file set to each KB and wait for ingestion to reach `status = ready` (poll `documents` table / API — ingestion is async per `CLAUDE.md`).
3. **Same question set against every KB.** Author one fixed set of test queries with expected/reference answers up front (10–30 questions spanning: fact lookup, multi-document synthesis, out-of-scope/negative questions to test hallucination resistance). Run this identical set against each KB's chat endpoint.
4. **Capture per query, per mode:**
   - the answer text and citations returned
   - `node_ids_visited` (tree nodes / chunk ids / graph node ids / wiki or openkb page ids)
   - wall-clock latency (ingestion time is captured once per KB in step 2; query latency is captured per question)
5. **Score each (query, answer, retrieved-context) triple** with the existing DeepEval metrics (§5).
6. **Aggregate** per mode: mean/median/pass-rate per metric, plus operational metrics (§5.2).

## 5. Metrics

### 5.1 Quality metrics (reuse existing framework, don't reinvent)

DocuMind already has a DeepEval-based eval pipeline in `backend/app/services/eval/` (`metrics.py`, `test_case.py`, `bedrock_judge.py`, `quality_gate.py`) driven by Bedrock Claude Sonnet 4.5 as judge. Reuse it as-is for consistency with production quality gates:

| Metric | Threshold (workspace default) | What it measures |
|---|---|---|
| Faithfulness | ≥ 0.85 | Is the answer grounded in the retrieved context? |
| Answer Relevancy | ≥ 0.80 | Does the answer address the question asked? |
| Contextual Precision | ≥ 0.75 | Are the retrieved chunks/nodes relevant, ranked well? |
| Contextual Recall | ≥ 0.75 | Does retrieval surface everything needed to answer? |
| Hallucination | ≤ 0.15 | Does the answer state things not supported by context? |

These thresholds live in `EvalConfig` per workspace and can be overridden; use workspace defaults unless the benchmark is specifically testing threshold tuning.

**Fixed:** `test_case.py::build_test_case` originally resolved `retrieval_context` only for `pageindex` (tree node lookup) and `vector` (chunk id lookup), leaving wiki/graph/openkb scores meaningless (empty context). It now also resolves WikiPage content, OpenKBPage content, and GraphNode descriptions (scoped by KB), so all 5 modes produce real faithfulness/precision/recall scores.

**Open gap — `doc_name` is not a real filename for 3 of 5 modes:** citations returned by chat (`CitationOut.doc_name`) are a genuine source-document filename for `pageindex` and `vector`, but for `wiki` and `openkb` it's the wiki-style page title, and for `graph` it's the graph entity name. Any benchmark metric that compares "which document(s) did this answer cite" against an expected document list (e.g. citation precision/recall) will only be reliable for `pageindex`/`vector` until the wiki/openkb/graph answer generators are changed to resolve `doc_name` through `source_doc_ids` back to the real filename. Flagging this now so it isn't discovered mid-benchmark; not yet fixed.

### 5.2 Operational metrics (new, not currently instrumented)

Capture alongside the quality metrics, per mode:

| Metric | How to capture |
|---|---|
| Ingestion time per document | timestamp document upload → `status=ready` transition |
| Ingestion failure rate | count of documents that fail to reach `ready` / fall back (e.g. PageIndex's single-node fallback when the tree LLM response is unparseable — that's a silent quality regression worth counting) |
| Query latency (p50/p95) | time from chat request to full SSE stream completion |
| Tokens / cost per query | LLM input+output tokens for tree navigation / retrieval / answer generation steps, priced against the active Bedrock model |
| Citation count per answer | proxy for how much source grounding each mode surfaces |

### 5.3 Suggested composite view

For the final report, present per mode: the 5 quality metrics (mean + pass-rate against threshold) side by side with ingestion time and query latency, so cost/speed tradeoffs are visible next to quality — a mode that scores marginally higher on faithfulness but takes 10x longer to ingest may not be the right default.

## 6. Optional finer-grained comparison

If useful, also break out `vector` mode's 3 retrieval sub-strategies (`vector`, `fulltext`, `hybrid`) as separate rows — they use the same ingestion pipeline but different retrieval logic, so this is a cheap way to get more signal without standing up new tree/graph/wiki builds.

## 7. Procedure to execute (once a target stack is available)

1. Stand up or point at a running DocuMind stack (`make up`, or a shared environment) with valid AWS/Bedrock credentials — the judge model and several RAG modes require live LLM calls.
2. Extend `test_case.py` per §5.1 gap if wiki/graph/openkb are in scope.
3. Create the KBs (§4.1), upload the dataset (§4.2), wait for ingestion, log ingestion metrics.
4. Run the fixed question set (§4.3) against each KB via the chat API, logging latency and node_ids per response.
5. For each stored `ChatMessage`, invoke the existing eval flow (`evaluate_response_async` / `build_metrics`) to get the 5 quality scores, or call `build_test_case` + DeepEval metrics directly for an out-of-band batch run instead of going through the async Celery queue.
6. Write every raw score to `docs/benchmark-results/<date>-results.json` (schema in `rag-benchmark-results.template.json`).
7. Roll up into a summary table and short written recommendation.

## 8. Deliverables from a completed run

- `*-results.json` — one row per (mode, document/question) with raw scores (machine-readable, see template).
- A short markdown summary — per-mode aggregate table + 3–5 sentence recommendation, no need for a separate doc/pptx unless requested.
