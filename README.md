# Financial RAG Engine

A production-grade **Retrieval-Augmented Generation** system for financial analysis. Query SEC filings, earnings transcripts, macroeconomic data, and financial news through a natural language interface powered by a 6-stage hybrid retrieval pipeline.

## Architecture

```
User Question
     │
     ▼
┌────────────────────────────────────────────────────────┐
│                   QUERY PIPELINE                       │
│                                                        │
│  1. Contextual Query Builder (conversation-aware)      │
│  2. Query Rewriter (LLM-optimized search terms)        │
│  3. HyDE (Hypothetical Document Embedding)             │
│  4. Hybrid Search (Vector + BM25 via RRF fusion)       │
│  5. HF Reranker (BGE-Reranker-v2-M3 via Inference API) │
│  6. Financial Synthesis (cite-backed expert answer)    │
│                                                        │
└────────────────────────────────────────────────────────┘
     │
     ▼
  Expert Analysis with Source Citations
```

## Data Sources

| Source | Type | Coverage | Documents/Ticker |
|--------|------|----------|-----------------|
| **FRED** | Macro indicators | GDP, CPI, FEDFUNDS, unemployment, 14 series total | 1 per series |
| **yFinance** | Equity fundamentals | Profile, income, balance sheet, cash flow, price | 5 per ticker |
| **SEC EDGAR** | 10-K / 10-Q filings | Business, risk factors, MD&A, legal, market risk | Up to 5 sections × 2 forms |
| **Earnings** | 8-K exhibits | Prepared remarks, CFO financials, Q&A, full text | Up to 4 sections × 8 quarters |
| **News** | Polygon.io | Ticker-specific + market-wide, 90-day lookback | Up to 50 per ticker |

## Tech Stack

| Layer | Technology |
|-------|------------|
| **LLM** | OpenRouter → Nvidia Nemotron 120B (free tier) |
| **Embeddings** | Nvidia Llama-Nemotron-Embed 1B (2048-dim, free tier) |
| **Reranker** | HuggingFace Inference API → BGE-Reranker-v2-M3 |
| **Database** | ParadeDB (PostgreSQL + pgvector + BM25) |
| **Backend** | FastAPI + SQLAlchemy (Optimized CPU-only stack) |
| **Frontend** | React + Vite |
| **Infrastructure** | Docker Compose

## Quick Start

### Prerequisites
- Docker & Docker Compose
- API keys: [OpenRouter](https://openrouter.ai/), [FRED](https://fred.stlouisfed.org/docs/api/api_key.html), [Polygon.io](https://polygon.io/)

### 1. Clone & Configure

```bash
git clone https://github.com/YOUR_USERNAME/Financial-RAG-Engine.git
cd Financial-RAG-Engine

cp .env.example .env
# Edit .env with your API keys
```

### 2. Launch

```bash
docker compose up --build
```

This starts three services:
- **FastAPI backend** → `http://localhost:8080`
- **React frontend** → `http://localhost:5173`
- **ParadeDB** → `localhost:5432`

### 3. Ingest Data

```bash
# Ingest all data sources
curl -X POST http://localhost:8080/rag/ingest

# OR ingest a specific source (fred, sec, yfinance, transcript, news)
curl -X POST http://localhost:8080/rag/ingest?source=fred
```

### 4. Query

Open `http://localhost:5173` and ask questions like:
- *"What was Apple's revenue last quarter?"*
- *"Did NVIDIA beat earnings estimates?"*
- *"What is the current federal funds rate and how does it compare to historical averages?"*

## Project Structure

```
Financial-RAG-Engine/
├── rag/
│   ├── api.py                  # FastAPI endpoints (/rag/query, /rag/ingest)
│   ├── llm_setup.py            # LLM + embedding + reranker initialization
│   ├── db_setup.py             # PostgreSQL/pgvector schema definition
│   ├── query_rewriter.py       # Stage 2: LLM query optimization
│   ├── hyde.py                 # Stage 3: Hypothetical Document Embedding
│   ├── hybrid_search.py        # Stage 4: Vector + BM25 + RRF fusion
│   ├── reranker.py             # Stage 5: Cross-encoder reranking
│   ├── contextual_query.py     # Stage 1: Conversation history integration
│   ├── synthesis.py            # Stage 6: Financial answer synthesis
│   └── ingestion/
│       ├── ingestion.py        # Orchestrator + chunking + embedding + storage
│       ├── config.py           # Ticker universe registry
│       ├── models.py           # FinancialDoc data contract
│       ├── fred_analyzer.py    # FRED macro data pipeline
│       ├── yfinance_analyzer.py# Equity fundamentals pipeline
│       ├── sec_analyzer.py     # SEC EDGAR filing parser
│       ├── transcript_analyzer.py  # Earnings call/press release parser
│       └── news_analyzer.py    # Polygon.io news pipeline
├── frontend/
│   ├── src/
│   │   ├── App.jsx             # Terminal-style chat interface
│   │   ├── main.jsx            # React entry point
│   │   └── ragchat.css         # Dark theme terminal UI
│   └── Dockerfile
├── db/
│   └── init.sql                # Database schema initialization
├── docker-compose.yml          # 3-service orchestration
├── Dockerfile                  # Backend container
├── requirements.txt            # Python dependencies
├── FINANCE_LOGIC.md            # Data logic specification
└── PLAN.md                     # Future roadmap
```

## API Reference

### `POST /rag/query`

```json
{
  "question": "What is Apple's current P/E ratio?",
  "history": [
    {"role": "user", "content": "Tell me about AAPL"},
    {"role": "assistant", "content": "Apple Inc. is a technology company..."}
  ]
}
```

**Response:**
```json
{
  "answer": "Based on the latest yFinance data...",
  "metadata": {
    "rewritten_query": "AAPL trailing P/E ratio 2025",
    "sources_count": 6,
    "history_turns_used": 2
  }
}
```

### `POST /rag/ingest`

Triggers the data ingestion orchestrator.

**Query Parameters:**
- `source` (optional): The specific data source to ingest (`fred`, `yfinance`, `sec`, `transcript`, or `news`). If omitted, all sources are ingested.

**Response:** Returns a map of sources to the number of new chunks successfully embedded and stored.

### `GET /health`

Health check endpoint for container orchestration.

## Key Design Decisions

- **Sentence-window chunking**: Each sentence is embedded individually, but ±2 surrounding sentences are stored as `window_text` for richer synthesis context
- **HyDE**: Generates a hypothetical answer to embed, improving vector search recall for financial queries
- **Reciprocal Rank Fusion (RRF)**: Merges vector similarity and BM25 keyword results with `k=60`, capturing both semantic meaning and exact financial tokens
- **Regime classification**: Every document is tagged with an economic/market regime label for state-aware reasoning
- **Idempotent ingestion**: SHA-256 chunk hashing ensures re-runs never duplicate data

## Environment Variables

See [`.env.example`](.env.example) for the full list. Key variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENROUTER_API_KEY` | ✅ | LLM and embedding API access |
| `HF_API_KEY` | ✅ | HuggingFace Inference API (for reranking) |
| `FRED_API_KEY` | ✅ | Federal Reserve economic data |
| `POLYGON_API_KEY` | ✅ | Financial news data |
| `SEC_EDGAR_IDENTITY` | ✅ | Your email (SEC fair access policy) |
| `DB_USER` / `DB_PASSWORD` | ✅ | PostgreSQL credentials |

## Roadmap

- **Apache Airflow integration** — Scheduled DAGs for automated daily/weekly data ingestion across all sources (FRED, yFinance, SEC, transcripts, news), replacing the current manual `/rag/ingest` trigger
- Causal linkage graphs between macro indicators for multi-hop reasoning
- Cross-entity narrative synthesis (pre-computed "Macro vs Market" overview docs)
- FMP Premium transcript integration for full Q&A session coverage

## License

This project is licensed under the [MIT License](LICENSE).
