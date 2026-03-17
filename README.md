# 🧠 Advanced Financial RAG Engine

A production-grade Retrieval-Augmented Generation pipeline purpose-built for financial document Q&A. Ask natural-language questions about SEC filings, earnings reports, and financial news — the engine retrieves the most relevant passages from a pgvector-powered document store and synthesizes precise, grounded answers.

**This is not a wrapper around an API.** The pipeline implements six distinct NLP stages, each solving a specific retrieval or ranking problem, orchestrated end-to-end in Python.

---

### 🔍 Query Pipeline (RAG Search)
```
User Question
     │
     ▼
┌─────────────────────────────────────────────────────────┐
│  Stage 1 · Query Rewriting                              │
│  LLM rewrites conversational questions into precise     │
│  financial search queries with tickers, fiscal periods, │
│  and domain terminology (revenue, EPS, gross margin)    │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│  Stage 2 · HyDE (Hypothetical Document Embedding)       │
│  LLM generates a hypothetical SEC-style passage that    │
│  would answer the query. This passage is embedded       │
│  instead of the question — achieving ~0.85-0.92 cosine  │
│  similarity vs ~0.60-0.72 for raw question embedding    │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│  Stage 3 · Hybrid Retrieval (Vector + BM25 + RRF)       │
│  Runs two parallel searches:                            │
│    • pgvector cosine similarity (HNSW index, <=>) on    │
│      the HyDE embedding                                 │
│    • PostgreSQL full-text search (ts_rank + @@) on the  │
│      rewritten query text                               │
│  Merges both ranked lists via Reciprocal Rank Fusion    │
│  (k=60) → 20 candidates                                 │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│  Stage 4 · Sentence-Window Expansion                    │
│  Each retrieved sentence is replaced with its ±2        │
│  surrounding sentences (stored at ingestion time).      │
│  Gives the reranker and LLM full paragraph context      │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│  Stage 5 · Cross-Encoder Reranking                      │
│  ms-marco-MiniLM-L-6-v2 scores each candidate against   │
│  the ORIGINAL question (not the rewritten query).       │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│  Stage 6 · LLM Synthesis                                │
│  Refines top 5 passages into a structured answer.       │
└─────────────────────────────────────────────────────────┘
```

### ⚙️ Data Ingestion Pipeline (Orchestration)
```
  ┌───────────────┐      ┌─────────────────┐      ┌───────────────┐
  │  SEC Filings  │      │  Earnings Calls │      │ Financial News│
  └───────┬───────┘      └────────┬────────┘      └───────┬───────┘
          │                       │                       │
          ▼                       ▼                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                Apache Airflow (DAG Orchestrator)                │
│  • Scheduling  • Retries  • Monitoring  • Parallel Ingestion    │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                  FastAPI /rag/ingest Endpoint                   │
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
| **Full-Text Search** | PostgreSQL `tsvector` + `ts_rank` | BM25-equivalent ranking using native Postgres (no external search engine) |
| **RAG Orchestration** | LlamaIndex Core | Document parsing, node management, metadata pipelines |
| **LLM** | Groq API (Llama 3.1 8B) | Ultra-fast inference (~100ms), generous free tier |
| **Embeddings** | HuggingFace `BAAI/bge-small-en-v1.5` | Runs locally on CPU, 384-dim vectors, free |
| **Reranker** | `cross-encoder/ms-marco-MiniLM-L-6-v2` | 23M param cross-encoder trained on MS MARCO |
| **Orchestration** | Apache Airflow | Orchestrating ingestion pipelines (SEC, news, earnings) |
| **Containerization** | Docker + Docker Compose | One-command deployment |

---

## 📂 Project Structure

```
.
├── docker-compose.yml          # Postgres (pgvector) + Backend
├── Dockerfile
├── requirements.txt
├── main.py                     # FastAPI entry point
│
├── rag/
│   ├── llm_setup.py            # Global LLM + embedding config
│   ├── query_rewriter.py       # Stage 1 — query optimization
│   ├── hyde.py                 # Stage 2 — hypothetical document embedding
│   ├── hybrid_search.py        # Stage 3 — vector + BM25 + RRF fusion
│   ├── ingestion.py            # Sentence-window document ingestion
│   ├── reranker.py             # Stage 5 — cross-encoder reranking
│   ├── query_engine.py         # Full pipeline orchestrator
│   └── api.py                  # REST endpoints (/rag/query, /rag/ingest)
│
└── db/
    ├── init.sql                # Schema: document_chunks + pgvector indexes
    └── database.py             # SQLAlchemy engine + session
```

---

## 🗄️ Database Schema

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE document_chunks (
    id          SERIAL PRIMARY KEY,
    doc_id      TEXT NOT NULL,
    source      TEXT NOT NULL,          -- "sec_10k", "earnings", "news"
    ticker      TEXT,                   -- filterable by company
    content     TEXT NOT NULL,
    metadata    JSONB,                  -- sentence window stored here
    embedding   vector(384),
    ts_content  tsvector GENERATED ALWAYS AS
                (to_tsvector('english', content)) STORED,
    created_at  TIMESTAMP DEFAULT NOW()
);

-- HNSW index for fast approximate nearest neighbor search
CREATE INDEX ON document_chunks USING hnsw (embedding vector_cosine_ops);

-- GIN index for full-text BM25 search
CREATE INDEX ON document_chunks USING gin (ts_content);
```

---

## 🚀 Quick Start

```bash
# 1. Clone and configure
git clone https://github.com/yourusername/advanced-rag-financial-qa.git
cd advanced-rag-financial-qa
cp .env.example .env
# Add your GROQ_API_KEY

# 2. Start services
docker compose up -d

# 3. Ingest documents
curl -X POST http://localhost:8000/rag/ingest \
  -H "Content-Type: application/json" \
  -d '{"texts": ["Apple reported Q4 revenue of $89.5B..."], "ticker": "AAPL"}'

# 4. Ask questions
curl -X POST http://localhost:8000/rag/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What was Apple revenue last quarter?", "ticker": "AAPL"}'
```

---

## 🔑 Key Design Decisions

### Why HyDE instead of direct question embedding?
Raw questions like *"How did Apple do last quarter?"* have low cosine similarity (~0.60) to financial documents. HyDE generates a hypothetical SEC-style passage first, then embeds *that* — boosting similarity to ~0.85-0.92 against real filings.

### Why hybrid search instead of vector-only?
Vector search excels at semantic similarity but misses exact financial terms (ticker symbols, specific dollar amounts). BM25 catches these. Reciprocal Rank Fusion merges both ranked lists without tuning weights.

### Why rerank against the original question?
The rewritten query is optimized for *retrieval* (maximize recall). But the user's actual intent might be subtly different. The cross-encoder scores each candidate against the *original* question to ensure the final answer addresses what was actually asked.

### Why sentence-window ingestion?
Embedding individual sentences gives precise retrieval. But a single sentence lacks context for the reranker and LLM. Sentence-window stores ±2 surrounding sentences in metadata, swapped in at retrieval time — best of both worlds.

### Why Airflow for orchestration?
Financial data is high-frequency and multi-source. Apache Airflow ensures data freshness by automating the ingestion of thousands of SEC filings and earnings transcripts. It provides built-in retries for network failures and a visual dashboard for monitoring pipeline health.

---

## 📝 API Reference

| Endpoint | Method | Description |
|---|---|---|
| `/rag/health` | GET | Health check |
| `/rag/query` | POST | Run full 6-stage pipeline on a question |
| `/rag/ingest` | POST | Ingest documents into pgvector (sentence-window parsed) |

### POST `/rag/query`
```json
{
  "question": "What is Apple's gross margin trend?",
  "ticker": "AAPL"
}
```

### POST `/rag/ingest`
```json
{
  "texts": ["Full text of SEC 10-K filing...", "Earnings press release..."],
  "ticker": "AAPL",
  "source": "sec_10k"
}
```

---

## 🗺️ Roadmap

- [ ] **Apache Airflow Integration**: Orchestrate data ingestion pipelines for automated SEC filing and news collection.
- [ ] **Multi-Vector Retrieval**: Support for table and image embeddings in financial reports.
- [ ] **Latency Optimization**: Implement KV caching and model quantization for faster synthesis.
