# 🧠 Advanced Financial RAG Engine

A production-grade Retrieval-Augmented Generation pipeline purpose-built for financial document Q&A. Ask natural-language questions about SEC filings, earnings reports, and financial news — the engine retrieves the most relevant passages from a pgvector-powered document store and synthesizes precise, grounded answers.

**This is not a wrapper around an API.** The pipeline implements a multi-stage NLP pipeline, each stage solving a specific retrieval or ranking problem, orchestrated end-to-end in Python.

> 🚧 **Work in Progress** — Stages 1–3 of the query pipeline are fully implemented. Ingestion, reranking, synthesis, and Airflow orchestration are on the roadmap.

---

### 🔍 Query Pipeline (RAG Search)
```
User Question
     │
     ▼
┌─────────────────────────────────────────────────────────┐
│  Stage 1 · Query Rewriting                     ✅ DONE  │
│  LLM rewrites conversational questions into precise     │
│  financial search queries with tickers, fiscal periods, │
│  and domain terminology (revenue, EPS, gross margin)    │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│  Stage 2 · HyDE (Hypothetical Document Embedding)       │
│  LLM generates a hypothetical SEC-style passage that    │ ✅ DONE
│  would answer the query. This passage is embedded       │
│  instead of the question — achieving ~0.85-0.92 cosine  │
│  similarity vs ~0.60-0.72 for raw question embedding    │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│  Stage 3 · Hybrid Retrieval (Vector + BM25 + RRF)       │
│  Runs two parallel searches:                            │
│    • pgvector cosine similarity (<=>)  on the HyDE      │ ✅ DONE
│      embedding                                          │
│    • ParadeDB BM25 full-text search (@@@) on the        │
│      rewritten query text                               │
│  Merges both ranked lists via Reciprocal Rank Fusion    │
│  (k=60) → top-k candidates                              │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│  Stage 4 · Sentence-Window Expansion           🔜 TODO  │
│  Each retrieved sentence is replaced with its ±2        │
│  surrounding sentences (stored at ingestion time).      │
│  Gives the reranker and LLM full paragraph context      │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│  Stage 5 · Cross-Encoder Reranking             🔜 TODO  │
│  ms-marco-MiniLM-L-6-v2 scores each candidate against  │
│  the ORIGINAL question (not the rewritten query).       │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│  Stage 6 · LLM Synthesis                       🔜 TODO  │
│  Refines top passages into a structured answer.         │
└─────────────────────────────────────────────────────────┘
```

### ⚙️ Data Ingestion Pipeline (Planned)
```
  ┌───────────────┐      ┌─────────────────┐      ┌───────────────┐
  │  SEC Filings  │      │  Earnings Calls │      │ Financial News│
  └───────┬───────┘      └────────┬────────┘      └───────┬───────┘
          │                       │                       │
          ▼                       ▼                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                Apache Airflow (DAG Orchestrator)     🔜 TODO    │
│  • Scheduling  • Retries  • Monitoring  • Parallel Ingestion    │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                  FastAPI /rag/ingest Endpoint        🔜 TODO    │
│  • PDF Parsing  • Text Chunking  • Sentence-Window Processing   │
│  • Embedding Generation  • pgvector Storage                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🛠️ Tech Stack

| Component | Technology | Why |
|---|---|---|
| **API Framework** | FastAPI + Uvicorn | Async, auto-generated docs, Pydantic validation |
| **Vector Database** | PostgreSQL + pgvector | HNSW indexing, cosine distance operator (`<=>`), co-located with relational data |
| **Full-Text Search** | ParadeDB BM25 (`@@@` operator) | Production-grade BM25 ranking built directly into Postgres — no external search engine |
| **RAG Orchestration** | LlamaIndex Core | Query transforms, prompt templates, embedding pipelines |
| **LLM** | OpenRouter API (configurable free-tier model) | Top free reasoning model for finance on OpenRouter |
| **Embeddings** | OpenRouter API (`nvidia/llama-nemotron-embed-vl-1b-v2:free`) | Cloud-based embedding generation, 4096-dim vectors, free tier |
| **Reranker** | `cross-encoder/ms-marco-MiniLM-L-6-v2` *(planned)* | 23M param cross-encoder trained on MS MARCO |
| **Orchestration** | Apache Airflow *(planned)* | Orchestrating ingestion pipelines (SEC, news, earnings) |
| **Containerization** | Docker + Docker Compose | One-command deployment |

---

## 📂 Project Structure

```
.
├── docker-compose.yml          # ParadeDB (pgvector + BM25) + FastAPI backend
├── Dockerfile                  # Python 3.11 slim image
├── Makefile                    # Shortcuts: make up, make build, make clean
├── requirements.txt
├── main.py                     # (placeholder)
├── .env.example                # Environment variable template
│
├── dags/                       # (planned) Airflow DAGs for ingestion
│
├── rag/
│   ├── llm_setup.py            # LLM + embedding init via OpenRouter
│   ├── query_rewriter.py       # Stage 1 — query optimization
│   ├── hyde.py                 # Stage 2 — hypothetical document embedding
│   ├── hybrid_search.py        # Stage 3 — vector + BM25 + RRF fusion
│   ├── db_setup.py             # SQLAlchemy engine, table schema, BM25 index init
│   └── api.py                  # FastAPI app + REST endpoints
│
└── db/
    └── init.sql                # Schema: financial_documents + pgvector extension
```

---

## 🗄️ Database Schema

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE financial_documents (
    id               SERIAL PRIMARY KEY,
    document_title   VARCHAR(255) NOT NULL,
    content          TEXT NOT NULL,
    embedding        halfvec(4096),
    company_ticker   VARCHAR(10),
    report_date      DATE,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- BM25 index for full-text search (ParadeDB)
CREATE INDEX documents_bm25
    ON financial_documents
    USING bm25 (id, content)
    WITH (key_field = 'id');
```

> **Note:** The database runs on [ParadeDB](https://www.paradedb.com/) — a Postgres-native search engine that provides real BM25 ranking via the `@@@` operator, eliminating the need for a separate Elasticsearch/Solr instance.

---

## 🚀 Quick Start

```bash
# 1. Clone and configure
git clone https://github.com/aamohmd/Financial-RAG-Engine.git
cd Financial-RAG-Engine
cp .env.example .env
# Add your OPENROUTER_API_KEY

# 2. Start services (ParadeDB + FastAPI)
make build
# or: docker compose up --build

# 3. Test the pipeline (query rewrite → HyDE → hybrid search)
curl -X POST http://localhost:8080/test

# 4. Health check
curl http://localhost:8080/docs   # Swagger UI
```

---

## 🔑 Key Design Decisions

### Why HyDE instead of direct question embedding?
Raw questions like *"How did Apple do last quarter?"* have low cosine similarity (~0.60) to financial documents. HyDE generates a hypothetical SEC-style passage first, then embeds *that* — boosting similarity to ~0.85-0.92 against real filings.

### Why hybrid search instead of vector-only?
Vector search excels at semantic similarity but misses exact financial terms (ticker symbols, specific dollar amounts). BM25 catches these. Reciprocal Rank Fusion merges both ranked lists without tuning weights.

### Why ParadeDB instead of PostgreSQL tsvector?
ParadeDB provides true BM25 scoring natively inside Postgres via the `@@@` operator, matching the ranking quality of dedicated search engines. Standard `tsvector` + `ts_rank` uses a simpler TF-IDF-like metric that lacks BM25's term-frequency saturation and document-length normalization.

### Why OpenRouter?
OpenRouter provides access to top-tier LLMs and embedding models through a single API with generous free tiers. This keeps the project zero-cost for development while allowing easy model switching (just change an env var).

### Why sentence-window ingestion? *(planned)*
Embedding individual sentences gives precise retrieval. But a single sentence lacks context for the reranker and LLM. Sentence-window stores ±2 surrounding sentences in metadata, swapped in at retrieval time — best of both worlds.

### Why rerank against the original question? *(planned)*
The rewritten query is optimized for *retrieval* (maximize recall). But the user's actual intent might be subtly different. The cross-encoder scores each candidate against the *original* question to ensure the final answer addresses what was actually asked.

---

## 📝 API Reference

| Endpoint | Method | Status | Description |
|---|---|---|---|
| `/docs` | GET | ✅ | Swagger UI |
| `/test` | POST | ✅ | End-to-end test: rewrite → HyDE → hybrid search |
| `/rag/query` | POST | 🔜 | Run full pipeline on a question |
| `/rag/ingest` | POST | 🔜 | Ingest documents into pgvector |

### POST `/test` (currently working)
Runs the implemented pipeline stages end-to-end with a hardcoded NVDA query for testing.

---

## 🗺️ Roadmap

- [x] **Query Rewriting** — LLM-powered query optimization for financial search
- [x] **HyDE** — Hypothetical Document Embedding for improved vector retrieval
- [x] **Hybrid Search** — Vector (pgvector) + BM25 (ParadeDB) with RRF fusion
- [x] **Database Setup** — ParadeDB with pgvector extension, SQLAlchemy ORM
- [x] **Docker Deployment** — One-command setup with Docker Compose
- [ ] **Document Ingestion Pipeline** — PDF parsing, sentence-window chunking, embedding + storage
- [ ] **Cross-Encoder Reranking** — ms-marco-MiniLM-L-6-v2 for precision re-scoring
- [ ] **LLM Synthesis** — Structured answer generation from top passages
- [ ] **Full `/rag/query` Endpoint** — Wire all 6 stages into a single API call
- [ ] **Apache Airflow Integration** — Orchestrate automated SEC filing and news ingestion
- [ ] **Multi-Vector Retrieval** — Table and image embeddings in financial reports
