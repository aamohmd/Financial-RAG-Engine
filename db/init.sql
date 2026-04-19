CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS financial_documents (
    id               SERIAL PRIMARY KEY,
    chunk_hash       VARCHAR(64) UNIQUE NOT NULL,       -- SHA-256 dedup key
    document_title   VARCHAR(255) NOT NULL,
    content          TEXT NOT NULL,                      -- sentence (embedded)
    window_text      TEXT,                               -- ±2 surrounding sentences (context)
    embedding        halfvec(2048),
    entity           VARCHAR(20),                        -- "GDP", "CPIAUCSL", "AAPL"
    entity_type      VARCHAR(20),                        -- "macro", "equity", "rate", "index"
    source           VARCHAR(20),                        -- "fred", "bea", "sec", etc.
    report_date      DATE,
    metadata         JSONB DEFAULT '{}'::jsonb,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);