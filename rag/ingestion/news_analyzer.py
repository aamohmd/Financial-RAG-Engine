# rag/ingestion/news_analyzer.py
"""
Financial News Ingestion & Normalization
========================================
Source: Polygon.io free tier
    - Unlimited historical articles
    - 5 requests/minute on free tier
    - Pre-tagged with ticker associations
    - Endpoint: /v2/reference/news

One article → one FinancialDoc with entity_type:
    news_equity  — ticker-specific company news
    news_macro   — Fed, economic data, macro events
    news_market  — broad market news (no specific ticker)
"""

import os
import hashlib
import time
import logging
import requests
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv
from .models import FinancialDoc

@dataclass(frozen=True)
class NewsSignals:
    event_type:       str
    sentiment_tone:   str
    tickers_mentioned: tuple[str, ...]
    macro_relevant:   bool
    publisher:        str

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
logger      = logging.getLogger(__name__)
POLYGON_KEY = os.getenv("POLYGON_API_KEY")
POLYGON_BASE = "https://api.polygon.io"

RELEVANT_CATEGORIES = frozenset({
    "earnings",
    "dividends",
    "mergers & acquisitions",
    "analyst ratings",
    "fda",
    "federal reserve",
    "economic data",
    "ipo",
    "buybacks",
    "guidance",
    "financials",
    "markets",
    "economy",
    "technology",
    "energy",
})

NOISE_TITLE_KEYWORDS = (
    "best credit card",
    "budgeting tips",
    "how to save",
    "celebrity",
    "horoscope",
    "crypto scam",
    "nft",
    "meme coin",
    "lottery",
    "personal finance tips",
    "mortgage calculator",
)

MIN_ARTICLE_CHARS = 200

EVENT_TYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "earnings_result": (
        "reports earnings", "quarterly results", "quarterly earnings",
        "q1 results", "q2 results", "q3 results", "q4 results",
        "annual results", "full year results", "beats estimates",
        "misses estimates", "earnings per share",
    ),
    "guidance_update": (
        "raises guidance", "lowers guidance", "updates guidance",
        "raises outlook", "lowers outlook", "withdraws guidance",
        "fiscal year guidance", "full year outlook",
    ),
    "analyst_action": (
        "price target", "upgrades", "downgrades", "initiates coverage",
        "outperform", "underperform", "buy rating", "sell rating",
        "neutral rating", "overweight", "underweight",
    ),
    "ma_event": (
        "acquisition", "acquires", "merger", "takeover", "buyout",
        "bid for", "deal valued", "purchase agreement",
    ),
    "fed_action": (
        "federal reserve", "fed raises", "fed cuts", "rate decision",
        "fomc", "interest rate", "powell", "basis points",
    ),
    "economic_data": (
        "cpi", "inflation data", "jobs report", "unemployment",
        "gdp growth", "retail sales", "pce data", "nonfarm payroll",
    ),
    "capital_allocation": (
        "buyback", "share repurchase", "dividend", "special dividend",
        "stock split", "spin-off",
    ),
    "legal_regulatory": (
        "sec investigation", "doj", "antitrust", "lawsuit",
        "regulatory approval", "fda approval", "settlement",
    ),
    "product_launch": (
        "launches", "unveils", "announces new", "introduces",
        "new product", "new service", "partnership",
    ),
    "market_move": (
        "surges", "plunges", "rallies", "drops", "falls",
        "hits 52-week", "all-time high", "all-time low",
    ),
}

POSITIVE_SENTIMENT_KEYWORDS = (
    "beats", "surges", "rallies", "record", "strong", "robust",
    "raises guidance", "upgrades", "outperform", "accelerates",
    "exceeds", "better than expected", "all-time high", "growth",
    "expands", "gains", "rises", "jumps", "breakthrough",
)

NEGATIVE_SENTIMENT_KEYWORDS = (
    "misses", "plunges", "drops", "falls", "weak", "disappoints",
    "lowers guidance", "downgrades", "underperform", "slows",
    "below expectations", "loss", "decline", "cuts", "layoffs",
    "recall", "investigation", "lawsuit", "warning",
)

MACRO_RELEVANCE_KEYWORDS = (
    "federal reserve", "fed", "interest rate", "inflation",
    "gdp", "unemployment", "recession", "economic growth",
    "treasury yield", "bond market", "monetary policy",
    "fiscal policy", "tariff", "trade war",
)

RECENCY_WEIGHTS: dict[str, float] = {
    "earnings_result":   0.9,
    "guidance_update":   0.9,
    "analyst_action":    0.6,
    "ma_event":          0.8,
    "fed_action":        0.9,
    "economic_data":     0.8,
    "capital_allocation":0.7,
    "legal_regulatory":  0.7,
    "product_launch":    0.5,
    "market_move":       0.3,
    "general":           0.4,
}

NO_NEWS_TICKERS = frozenset({
    "SPY", "QQQ", "DIA", "IWM",
    "XLK", "XLF", "XLE", "XLV", "XLI",
    "XLY", "XLP", "XLU", "XLRE", "XLB", "XLC",
})

def classify_news_regime(signals: NewsSignals) -> str:
    et = signals.event_type
    st = signals.sentiment_tone

    if et == "earnings_result":
        return "earnings_beat" if st == "positive" else (
               "earnings_miss" if st == "negative" else "earnings_inline")

    if et == "guidance_update":
        return "guidance_raised" if st == "positive" else (
               "guidance_lowered" if st == "negative" else "guidance_maintained")

    if et == "analyst_action":
        return "analyst_upgrade" if st == "positive" else (
               "analyst_downgrade" if st == "negative" else "analyst_neutral")

    if et == "ma_event":          return "ma_activity"
    if et == "fed_action":        return "fed_policy_news"
    if et == "economic_data":     return "macro_data_release"
    if et == "legal_regulatory":
        return "regulatory_risk" if st == "negative" else "regulatory_approval"
    if et == "capital_allocation":return "capital_return"
    if et == "market_move":
        return "bullish_momentum" if st == "positive" else "bearish_momentum"

    return "general_news"

def fetch_ticker_news(
    ticker:     str,
    days_back:  int = 90,
    limit:      int = 50,
    _retries:   int = 3,
) -> list[dict]:
    published_after = (
        datetime.now(timezone.utc) - timedelta(days=days_back)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    resp = requests.get(
        f"{POLYGON_BASE}/v2/reference/news",
        params={
            "ticker":          ticker,
            "published_utc.gte": published_after,
            "limit":           limit,
            "sort":            "published_utc",
            "order":           "desc",
            "apiKey":          POLYGON_KEY,
        },
        timeout=20,
    )
    if resp.status_code == 429:
        if _retries <= 0:
            logger.error("[News] %s: max retries exceeded on 429", ticker)
            return []
        logger.warning("[News] Rate limited — sleeping 15s (%d retries left)", _retries)
        time.sleep(15)
        return fetch_ticker_news(ticker, days_back, limit, _retries - 1)
    resp.raise_for_status()
    return resp.json().get("results", [])

def fetch_market_news(days_back: int = 7, limit: int = 50, _retries: int = 3) -> list[dict]:
    published_after = (
        datetime.now(timezone.utc) - timedelta(days=days_back)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    resp = requests.get(
        f"{POLYGON_BASE}/v2/reference/news",
        params={
            "published_utc.gte": published_after,
            "limit":             limit,
            "sort":              "published_utc",
            "order":             "desc",
            "apiKey":            POLYGON_KEY,
        },
        timeout=20,
    )
    if resp.status_code == 429:
        if _retries <= 0:
            logger.error("[News] Market feed: max retries exceeded on 429")
            return []
        logger.warning("[News] Rate limited on market feed — sleeping 15s (%d retries left)", _retries)
        time.sleep(15)
        return fetch_market_news(days_back, limit, _retries - 1)
    resp.raise_for_status()
    return resp.json().get("results", [])

def article_hash(article: dict) -> str:
    key = f"{article.get('title', '')}_{article.get('published_utc', '')[:10]}"
    return hashlib.md5(key.encode()).hexdigest()

def deduplicate(articles: list[dict]) -> list[dict]:
    seen   = set()
    unique = []
    for article in articles:
        h = article_hash(article)
        if h not in seen:
            seen.add(h)
            unique.append(article)
    return unique

def is_relevant(article: dict) -> bool:
    title   = article.get("title", "").lower()
    summary = article.get("description", "") or ""

    if any(noise in title for noise in NOISE_TITLE_KEYWORDS):
        return False

    if len(summary) < MIN_ARTICLE_CHARS:
        return False

    return True

def filter_relevant(articles: list[dict]) -> list[dict]:
    return [a for a in articles if is_relevant(a)]

def detect_event_type(title: str, summary: str) -> str:
    text = (title + " " + summary).lower()
    for event_type, keywords in EVENT_TYPE_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return event_type
    return "general"

def detect_sentiment(title: str, summary: str) -> str:
    text = (title + " " + summary).lower()
    pos  = sum(1 for kw in POSITIVE_SENTIMENT_KEYWORDS if kw in text)
    neg  = sum(1 for kw in NEGATIVE_SENTIMENT_KEYWORDS if kw in text)
    if pos > neg:   return "positive"
    if neg > pos:   return "negative"
    return "neutral"

def detect_macro_relevance(title: str, summary: str) -> bool:
    text = (title + " " + summary).lower()
    return any(kw in text for kw in MACRO_RELEVANCE_KEYWORDS)

def extract_news_signals(article: dict) -> NewsSignals:
    title     = article.get("title", "")
    summary   = article.get("description", "") or ""
    tickers   = tuple(article.get("tickers", []))
    publisher = article.get("publisher", {}).get("name", "unknown")

    event_type     = detect_event_type(title, summary)
    sentiment_tone = detect_sentiment(title, summary)
    macro_relevant = detect_macro_relevance(title, summary)

    return NewsSignals(
        event_type        = event_type,
        sentiment_tone    = sentiment_tone,
        tickers_mentioned = tickers,
        macro_relevant    = macro_relevant,
        publisher         = publisher,
    )

def build_news_body(
    article:  dict,
    signals:  NewsSignals,
    primary_ticker: str | None,
) -> str:
    title     = article.get("title", "")
    summary   = article.get("description", "") or ""
    pub_date  = article.get("published_utc", "")[:10]
    publisher = signals.publisher

    if primary_ticker:
        header = f"{primary_ticker} — {signals.event_type.replace('_', ' ').title()} — {pub_date}. "
    else:
        header = f"Market News — {signals.event_type.replace('_', ' ').title()} — {pub_date}. "

    parts = []
    if signals.tickers_mentioned:
        parts.append(f"Companies mentioned: {', '.join(signals.tickers_mentioned[:5])}.")
    if signals.macro_relevant:
        parts.append("Macro-relevant event.")
    signal_str = " ".join(parts)

    return f"{header}{signal_str} Source: {publisher}. {title}. {summary}"

def determine_entity_type(signals: NewsSignals, primary_ticker: str | None) -> str:
    if signals.macro_relevant and not primary_ticker:
        return "news_macro"
    if primary_ticker:
        return "news_equity"
    return "news_market"

def normalize_news_article(
    article:        dict,
    primary_ticker: str | None = None,
) -> FinancialDoc | None:
    signals    = extract_news_signals(article)
    regime     = classify_news_regime(signals)
    pub_date   = article.get("published_utc", "")[:10]
    entity     = primary_ticker or "MARKET"
    entity_type = determine_entity_type(signals, primary_ticker)

    body = build_news_body(article, signals, primary_ticker)
    if not body.strip():
        return None

    recency_weight = RECENCY_WEIGHTS.get(signals.event_type, 0.4)

    tags = ["news", entity_type, signals.event_type, signals.sentiment_tone]
    if primary_ticker:
        tags.append(primary_ticker.lower())
    if signals.macro_relevant:
        tags.append("macro_relevant")

    return FinancialDoc(
        source      = "news",
        entity      = entity,
        entity_type = entity_type,
        date        = pub_date,
        title       = article.get("title", "")[:200],
        body        = body,
        tags        = tags,
        regime      = regime,
        meta        = {
            "article_url":       article.get("article_url", ""),
            "publisher":         signals.publisher,
            "event_type":        signals.event_type,
            "sentiment_tone":    signals.sentiment_tone,
            "tickers_mentioned": list(signals.tickers_mentioned),
            "macro_relevant":    signals.macro_relevant,
            "recency_weight":    recency_weight,
            "published_utc":     article.get("published_utc", ""),
            "article_hash":      article_hash(article),
        },
    )

def load_all_news(
    tickers:  list[str],
    days_back: int = 90,
) -> list[FinancialDoc]:

    all_raw  = []
    all_docs = []

    for ticker in tickers:
        if ticker in NO_NEWS_TICKERS:
            continue
        try:
            articles = fetch_ticker_news(ticker, days_back=days_back)
            for a in articles:
                a["primary_ticker"] = ticker
            all_raw.extend(articles)
            logger.info("[News] %s → %d raw articles", ticker, len(articles))
        except Exception as e:
            logger.error("[News] %s failed: %s", ticker, e)
        time.sleep(12)

    try:
        market_articles = fetch_market_news(days_back=min(days_back, 7))
        for a in market_articles:
            a["primary_ticker"] = None
        all_raw.extend(market_articles)
        logger.info("[News] Market feed → %d raw articles", len(market_articles))
    except Exception as e:
        logger.error("[News] Market feed failed: %s", e)

    unique = deduplicate(all_raw)
    logger.info("[News] %d raw → %d after dedup", len(all_raw), len(unique))

    relevant = filter_relevant(unique)
    logger.info("[News] %d after relevance filter", len(relevant))

    for article in relevant:
        doc = normalize_news_article(
            article        = article,
            primary_ticker = article.pop("primary_ticker", None),
        )
        if doc:
            all_docs.append(doc)

    logger.info("[News] → %d FinancialDocs", len(all_docs))
    return all_docs
