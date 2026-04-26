## Financial Data Logic Canonical Specification

This document is the source of truth for how financial data is fetched, normalized, labeled, deduplicated, and prepared for retrieval in this repository.

It covers:
- Data contracts shared across all sources
- Source-specific extraction and regime logic
- Deduplication/idempotency rules
- Retrieval fusion behavior and ranking intent
- Data quality gates and operational checks

---

## 1) Canonical Data Contract

Every source must emit one or more `FinancialDoc` objects with this semantic contract:

- `source`: `fred` | `yfinance` | `sec` | `transcript` | `news`
- `entity`: primary topic key (for example `AAPL`, `GDP`, `FEDFUNDS`)
- `entity_type`: source-specific subtype used by retrieval filters
- `date`: canonical report/event date in ISO format
- `title`: concise retrieval title
- `body`: natural language narrative (the text actually embedded)
- `tags`: retrieval routing hints
- `regime`: classification label used for macro/market state reasoning
- `meta`: structured facts used for scoring, filtering, auditing

Principle: one logical financial observation should map to one logical document before chunking.

---

## 2) Source Coverage (Implemented)

### 2.1 FRED Macro + BEA-Equivalent Series

FRED is the macro backbone. BEA core themes are ingested via FRED proxy series IDs to avoid a separate BEA ingestion surface.

Active macro/rate/index series:
- `GDP`
- `A191RL1Q225SBEA` (real GDP growth)
- `DPCERL1Q225SBEA` (real PCE growth)
- `A006RL1Q225SBEA` (real investment growth)
- `PI`, `PCE`, `PSAVERT`, `CP`
- `CPIAUCSL`, `UNRATE`, `FEDFUNDS`, `GS10`, `T10YIE`, `NASDAQCOM`

BEA table intent mapping:
- GDP growth: `A191RL1Q225SBEA`
- Personal income/savings: `PI`, `PSAVERT`
- Corporate profits: `CP`

Core computations:
- Valid observations drop `.`/null values
- Short-term change uses latest vs previous observation
- YoY picks the nearest observation at least 365 days older
- YoY % = `((latest - year_ago) / abs(year_ago)) * 100`
- Rolling statistics use a 10-year window fallback to full history

Narrative synthesis:
- Output body is dense text (not raw table dump)
- Includes absolute level, period-over-period move, YoY context, distance from mean
- Optional z-score extreme sentence when threshold is breached

Regime classification highlights:
- Inflation: `high_inflation`, `elevated_inflation`, `stable_prices`, `deflation`
- Labor: `full_employment`, `tight_labor`, `slack_labor`
- Policy/yields: `restrictive`/`neutral`/`accommodative`, yield environment regimes
- Equity index: `bull_market`, `neutral_market`, `bear_market`

Output granularity:
- One `FinancialDoc` per series (high retrieval precision)

### 2.2 yfinance Equity Fundamentals + Market Structure

One ticker yields up to 5 documents:
- `equity_profile`
- `equity_income`
- `equity_balance`
- `equity_cashflow`
- `equity_price`

Coverage details:
- Profile: valuation multiples, EPS, dividend, analyst recommendation metadata
- Income: revenue/profit lines, derived gross margin and net margin
- Balance: asset/liability/debt snapshots for leverage reasoning
- Cash flow: operating CF, capex, derived FCF
- Price: 52-week positioning, MA50/MA200 structure, beta interpretation

Regime examples:
- Profile valuation regimes: `growth_premium`, `fairly_valued`, `value`, `unprofitable`
- Income margin regimes: `high_margin`, `moderate_margin`, `thin_margin`, `unprofitable`
- Price regimes: `near_52w_high`, `uptrend`, `neutral_trend`, `pullback`, `bear_territory`

Resilience behavior:
- Missing frames degrade to narrative with no hard failure
- One-second delay per ticker for rate-limit safety

### 2.3 SEC EDGAR (10-K + 10-Q)

Latest filing per form is normalized into section-level documents.

Section map:
- 10-K:
	- `Item 1` -> Business
	- `Item 1A` -> Risk Factors
	- `Item 7` -> MD&A
	- `Item 7A` -> Quantitative Market Risk
	- `Item 3` -> Legal Proceedings
- 10-Q:
	- `Part I, Item 2` -> MD&A
	- `Part I, Item 3` -> Quantitative Market Risk
	- `Part II, Item 1` -> Legal Proceedings

Important correctness rule:
- 10-Q legal must come from `Part II, Item 1` (not `Item 1` shorthand), otherwise financial statements are mislabeled as legal content.

Normalization behavior:
- Section text shorter than 200 chars is skipped
- Section text is truncated by per-section max-char limits
- `meta` includes accession number, fiscal period, section key, char count, truncation flag

Regime tagging:
- Rule-based keyword tagging for MD&A and risk sections (`expansion`, `restructuring`, `regulatory_risk`, `macro_risk`, etc.)

### 2.4 Earnings Transcripts / Press Releases (8-K Exhibit Path)

Primary free-tier pathway:
- SEC 8-K attachments (`EX-99.1`, `99.1`, `EX-99`, `99`)
- Optional FMP transcript API helper exists, but 8-K path is primary current ingestion path

Filtering and parsing:
- Minimum document length gate: 2000 characters
- Earnings relevance keyword gate on early content
- `Exhibit 99.x` boilerplate is stripped
- Quarter/year inferred from text with date-based fallback

Segmentation:
- Detects press release vs call-like transcript
- For calls: speaker-turn parsing + role detection + Q&A boundary detection
- Sections emitted: `remarks`, `financials`, `qa`, `full` (as available)

Signal extraction:
- Guidance tone: raised/lowered/maintained/none
- Beat/miss
- Positive/negative topic sets (for example `margin_expansion`, `strong_demand`)
- Macro concern flag

Regime outputs:
- `bullish_guidance`, `bearish_guidance`, `solid_quarter`, `disappointing_quarter`, `positive_tone`, `cautious_tone`, `neutral_tone`

Ticker exclusions:
- ETF/index tickers are skipped by design (`SPY`, `QQQ`, sectors, etc.)

### 2.5 Financial News (Polygon)

Feeds:
- Ticker feed: up to 50 articles per ticker, default 90-day lookback
- Market feed: up to 50 articles, capped to 7-day horizon

Primary-ticker strategy:
- Articles fetched for ticker T are stored once with `_primary_ticker = T`
- Multi-ticker mentions are preserved in metadata but retrieval entity remains primary ticker
- This prevents cross-ticker dilution from incidental mentions

Deduplication:
- Dedup key = `md5(title + published_date[:10])`
- URL is intentionally not the dedup key due to syndication variance

Relevance filters:
- Noise-title blacklist (consumer-finance spam patterns)
- Minimum summary size (`MIN_ARTICLE_CHARS = 200`)

Signal extraction:
- Event type classification (`earnings_result`, `guidance_update`, `analyst_action`, etc.)
- Sentiment classification (`positive`, `negative`, `neutral`)
- Macro relevance flag
- Tickers mentioned extracted directly from Polygon list-of-strings payload

Entity types:
- `news_equity` — ticker-specific company news
- `news_macro` — Fed, economic data, macro events (no primary ticker)
- `news_market` — broad market news

Recency weighting:
- Event-specific weights are embedded in metadata as `recency_weight`
- Intended retrieval behavior: combine semantic score with event weight and time decay

Resilience:
- All fetch functions have a `_retries=3` depth limit to prevent infinite recursion on persistent 429 rate limits

---

## 3) Active Universe Control

Ticker universe is governed by `TickerConfig` / `TICKER_REGISTRY` in `ingestion/config.py`.

Current active tier-1 tickers (10):
- **Technology:** AAPL, MSFT, NVDA, GOOGL
- **Consumer/Cyclical:** AMZN, TSLA
- **Communication Services:** META
- **Financial Services:** JPM, GS
- **Index:** SPY

ETF/index tickers (SPY) are automatically excluded from SEC filings, transcripts, and news ingestion where they are not applicable.

Operational rule: data-source loaders default to tier-1 tickers when no explicit ticker list is provided. New tickers can be added by inserting a `TickerConfig(tier=1, sector="...")` entry.

---

## 4) Chunking, Hashing, and Idempotency

### 4.1 Chunking strategy

- Standard sources (`fred`, `yfinance`, `sec`, `news`) use sentence-window chunking:
	- Each sentence is embedded as `content`
	- `window_text` stores +/-2 sentence context
- `transcript` is treated as full-section chunk (no sentence split) to preserve discourse continuity

### 4.2 Deduplication keys

- Generic sentence chunks: `sha256(sentence | entity | date)`
- Transcript chunks: `sha256(section | entity | date)`
	- This is semantic-id dedup to prevent duplicate embeddings from reruns with slightly different prose

### 4.3 Database idempotency contract

- `financial_documents.chunk_hash` is unique
- Upsert/insertion logic must respect `chunk_hash` uniqueness to avoid duplicate retrieval candidates

---

---

## 5) Retrieval and Ranking Logic

### 5.1 Hybrid Search Fusion
Hybrid retrieval merges:
- Vector search (`<=>`) against embeddings
- BM25 keyword search (`@@@`) against text content

Fusion method:
- Reciprocal Rank Fusion (RRF)
- Constant: `RRF_K = 60`
- Score formula: `sum(1 / (RRF_K + rank_i))`

### 5.2 AI Reranking (Local FlashRank)
The top candidates from the RRF fusion are passed to a local cross-encoder model for high-precision prioritization.
- **Model**: `ms-marco-TinyBERT-L-2-v2` (via FlashRank)
- **Logic**: A local CPU-based cross-encoder re-evaluates retrieval candidates against the full user query. This ensures the most salient financial evidence is prioritized for final synthesis without external API dependencies.

---

## 6) Data Quality Rules and Validation Checklist

### 6.1 Mandatory source checks

- FRED:
	- No `.` raw values in normalized stats
	- YoY fields null only when insufficient history
- yfinance:
	- Statement docs should contain at least one numeric line item or explicit unavailability narrative
- SEC:
	- 10-Q legal section must map to `Part II, Item 1`
	- `accession_number` present in metadata
- Transcripts:
	- Reject near-empty delivery stubs via min char threshold
	- Quarter/year extraction must match release text when present
- News:
	- `tickers_mentioned` should not be systematically empty
	- Dedup should materially reduce raw count after multi-ticker fetch

### 6.2 Retrieval quality safeguards

- Avoid storing mislabeled sections (especially SEC 10-Q legal)
- Avoid duplicate transcript embeddings for the same `(ticker, date, section)`
- Prefer high-signal narratives over boilerplate and press footer text

---

## 7) Known Caveats (Current State)

- News relevance currently uses title-noise + summary-length filters; deeper ticker-specific salience scoring is a future enhancement.
- News deduplication uses MD5 hashing (sufficient for dedup but not cryptographically aligned with the SHA-256 used elsewhere).
- Earnings transcript ingestion relies on the free 8-K exhibit path; full interactive Q&A requires FMP Premium (planned).

---

## 8) Operational Playbook

Recommended refresh order:
1. FRED macro/rates/index
2. yfinance ticker fundamentals
3. SEC filings (10-K/10-Q)
4. Transcripts (8-K exhibits)
5. News (ticker + market)

When fixing parsing/classification bugs in an existing source:
1. Purge affected source rows from storage
2. Re-ingest the source with corrected logic
3. Validate sample docs across body + metadata + regime labels

---

## 9) Guiding Principles

- Prefer deterministic, explainable rule logic over opaque transformations.
- Preserve provenance in metadata (accession IDs, article URLs, event types).
- Keep one document focused on one dominant financial idea whenever possible.
- Optimize for retrieval precision first, then synthesis quality.

