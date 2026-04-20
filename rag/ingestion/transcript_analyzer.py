"""
Earnings Transcript & Press Release Ingestion Pipeline
======================================================
Identifies, fetches, and normalizes corporate earnings communications from 
SEC 8-K exhibits (Free Tier) and FMP Transcript APIs (Premium Tier).

Pipeline Stages:
1. Sourcing:          Retrieves 8-K "Prepared Remarks" or FMP formal transcripts.
2. Signal Extraction: Detects guidance shifts, earnings beats/misses, and macro headwinds.
3. Parsing:           Segments content into 'Remarks', 'CFO Financials', and 'Q&A'.
4. Normalization:     Packages synthesized narratives into the FinancialDoc interface.
"""

import re
import os
import time
import logging
import requests
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv
from edgar import Company, set_identity

from .models import FinancialDoc
from .config import TICKER_REGISTRY

@dataclass(frozen=True)
class TranscriptSectionConfig:
    name:        str
    entity_type: str
    tags:        tuple[str, ...]
    max_chars:   int = 20_000

@dataclass(frozen=True)
class TranscriptSignals:
    guidance_tone:   str
    beat_miss:       str
    positive_topics: frozenset
    negative_topics: frozenset
    macro_concerns:  bool

@dataclass
class SpeakerTurn:
    speaker: str
    role:    str
    section: str
    text:    str

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

logger   = logging.getLogger(__name__)
FMP_KEY  = os.getenv("FMP_API_KEY")
FMP_BASE = "https://financialmodelingprep.com/api/v3"
SEC_ID   = os.getenv("SEC_EDGAR_IDENTITY", "admin@financial-rag.com")

NO_TRANSCRIPT_TICKERS = frozenset({
    "SPY", "QQQ", "DIA", "IWM", "GLD", "TLT", "HYG",
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLRE", "XLB", "XLC",
})

TRANSCRIPT_SECTIONS: dict[str, TranscriptSectionConfig] = {
    "remarks": TranscriptSectionConfig(
        name="Management Prepared Remarks", entity_type="transcript_remarks",
        tags=("transcript", "management", "prepared_remarks", "earnings"), max_chars=20_000,
    ),
    "financials": TranscriptSectionConfig(
        name="CFO Financial Discussion", entity_type="transcript_financials",
        tags=("transcript", "financials", "guidance", "cfo", "earnings"), max_chars=12_000,
    ),
    "qa": TranscriptSectionConfig(
        name="Q&A Session", entity_type="transcript_qa",
        tags=("transcript", "qa", "analysts", "earnings"), max_chars=24_000,
    ),
    "full": TranscriptSectionConfig(
        name="Full Transcript", entity_type="transcript_full",
        tags=("transcript", "full", "earnings"), max_chars=40_000,
    ),
}

EXECUTIVE_TITLES    = ("ceo", "chief executive", "cfo", "chief financial", "coo", "chief operating", "cto", "chief technology", "president", "chairman", "vice president", "vp ", "director")
OPERATOR_NAMES      = ("operator", "moderator", "conference")
CFO_TITLES          = ("cfo", "chief financial officer", "finance", "financial officer")
ANALYST_INDICATORS  = ("analyst", "research", "capital", "securities", "partners", "management llc", "asset management", "goldman", "morgan", "jp morgan", "barclays", "ubs", "citi", "bank of america", "wells fargo")

GUIDANCE_RAISED_KEYWORDS    = ("raising guidance", "raising our guidance", "raising full-year", "raising fiscal", "increased our guidance", "raising outlook", "raising revenue guidance", "raising eps guidance", "above the high end", "above our previous guidance", "raising the midpoint")
GUIDANCE_LOWERED_KEYWORDS   = ("lowering guidance", "lowering our guidance", "reducing guidance", "reducing our outlook", "below our previous", "lowering full-year", "withdrawal of guidance", "suspending guidance", "below the low end")
GUIDANCE_MAINTAINED_KEYWORDS= ("reaffirming guidance", "reaffirm our guidance", "maintaining guidance", "maintaining our outlook", "consistent with our prior", "no change to guidance")
BEAT_KEYWORDS               = ("exceeded expectations", "beat expectations", "above consensus", "above street estimates", "record revenue", "record earnings", "record quarter", "all-time high", "better than expected")
MISS_KEYWORDS               = ("below expectations", "missed expectations", "below consensus", "below street", "came in below", "fell short", "disappointed")
MACRO_CONCERN_KEYWORDS      = ("macro uncertainty", "macroeconomic headwinds", "tariff", "trade policy", "foreign exchange headwind", "fx headwind", "interest rate pressure", "rate environment", "inflation pressure", "inflationary", "consumer weakness", "demand softness", "supply chain", "geopolitical")

POSITIVE_TOPIC_KEYWORDS: dict[str, tuple] = {
    "ai_momentum":      ("artificial intelligence", "ai demand", "ai infrastructure", "generative ai", "ai adoption", "ai workloads", "ai revenue"),
    "margin_expansion": ("margin expansion", "margin improvement", "expanding margins", "operating leverage", "gross margin expansion", "strong margins", "record margins"),
    "strong_demand":    ("strong demand", "robust demand", "record demand", "strong backlog", "strong pipeline", "pipeline growth", "unprecedented demand", "best-ever quarter", "record-breaking", "all-time record", "better than our expectations"),
    "buyback_dividend": ("share repurchase", "buyback", "returning capital", "dividend increase", "special dividend"),
}
NEGATIVE_TOPIC_KEYWORDS: dict[str, tuple] = {
    "margin_compression": ("margin compression", "margin pressure", "declining margins", "gross margin decline", "pricing pressure"),
    "revenue_headwind":   ("revenue headwind", "revenue pressure", "revenue decline", "top-line pressure", "volume decline"),
    "cost_pressure":      ("cost pressure", "rising costs", "cost inflation", "elevated costs", "cost headwind"),
    "competition":        ("competitive pressure", "increased competition", "market share loss", "pricing competition"),
}

def match(text_lower: str, keywords: tuple) -> bool:
    return any(k in text_lower for k in keywords)

def strip_boilerplate(text: str) -> str:
    boilerplate_markers = (
        "forward-looking statements",
        "private securities litigation reform act",
        "these statements involve risks and uncertainties",
        "actual results may differ materially",
        "note to editors",
        "press contact",
        "investor relations contact",
        "© 20",
    )
    text_lower = text.lower()
    cutoff = len(text)
    for marker in boilerplate_markers:
        idx = text_lower.find(marker)
        if idx != -1 and idx < cutoff:
            cutoff = idx
    return text[:cutoff]

def estimate_quarter(filing_date) -> int:
    month = filing_date.month
    if month in (1, 2):   return 4
    if month in (4, 5):   return 1
    if month in (7, 8):   return 2
    if month in (10, 11): return 3
    return 1

def extract_period_from_text(text: str, filing_date) -> tuple[int, int]:
    text_lower = text[:3000].lower()
    quarter_words = {
        "first quarter": 1, "second quarter": 2,
        "third quarter": 3, "fourth quarter": 4,
        "q1 ": 1, "q2 ": 2, "q3 ": 3, "q4 ": 4,
    }
    detected_q = None
    for phrase, q_num in quarter_words.items():
        if phrase in text_lower:
            detected_q = q_num
            break

    year_match = re.search(r"\b(20\d{2})\b", text[:1000])
    detected_year = int(year_match.group(1)) if year_match else filing_date.year

    if detected_q:
        return detected_q, detected_year

    return estimate_quarter(filing_date), filing_date.year

def clean_exhibit_text(text: str) -> str:
    text = re.sub(r"(?i)exhibit\s+99\.\d+\s*", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [line.rstrip() for line in text.split("\n")]
    text  = "\n".join(lines)
    return text.strip()

def extract_signals(content: str) -> TranscriptSignals:
    clean = strip_boilerplate(content)
    tl    = clean.lower()
    
    if match(tl, GUIDANCE_RAISED_KEYWORDS):     guidance = "raised"
    elif match(tl, GUIDANCE_LOWERED_KEYWORDS):  guidance = "lowered"
    elif match(tl, GUIDANCE_MAINTAINED_KEYWORDS): guidance = "maintained"
    else:                                          guidance = "none"

    beat_miss = "beat" if match(tl, BEAT_KEYWORDS) else ("miss" if match(tl, MISS_KEYWORDS) else "none")
    pos = frozenset(t for t, kws in POSITIVE_TOPIC_KEYWORDS.items() if match(tl, kws))
    neg = frozenset(t for t, kws in NEGATIVE_TOPIC_KEYWORDS.items() if match(tl, kws))
    return TranscriptSignals(guidance, beat_miss, pos, neg, match(tl, MACRO_CONCERN_KEYWORDS))

def classify_transcript_regime(signals: TranscriptSignals) -> str:
    if signals.guidance_tone == "raised":   return "bullish_guidance"
    if signals.guidance_tone == "lowered":  return "bearish_guidance"
    if signals.beat_miss == "beat" and signals.guidance_tone == "maintained": return "solid_quarter"
    if signals.beat_miss == "miss":         return "disappointing_quarter"
    n_pos, n_neg = len(signals.positive_topics), len(signals.negative_topics)
    if n_pos > n_neg and not signals.macro_concerns: return "positive_tone"
    if n_neg > n_pos or signals.macro_concerns:      return "cautious_tone"
    if signals.beat_miss == "beat":                  return "solid_quarter"
    return "neutral_tone"

def classify_speaker_role(speaker: str) -> str:
    s = speaker.lower()
    if any(t in s for t in OPERATOR_NAMES):    return "operator"
    if any(t in s for t in CFO_TITLES):        return "cfo"
    if any(t in s for t in EXECUTIVE_TITLES):  return "executive"
    if any(t in s for t in ANALYST_INDICATORS):return "analyst"
    return "unknown"

def detect_qa_boundary(turns: list) -> int:
    for i, turn in enumerate(turns):
        if turn.role == "analyst": return i
        if turn.role == "operator" and any(
            p in turn.text.lower() for p in ("question", "q&a", "open the floor", "take questions")
        ):
            return i
    return len(turns)

def parse_transcript(content: str) -> list[SpeakerTurn]:
    pattern = re.compile(r"^([A-Z][^:\n]{2,60}):\s*", re.MULTILINE)
    parts   = pattern.split(content.strip())
    turns   = []
    it      = iter(parts[1:])
    for speaker, text in zip(it, it):
        speaker, text = speaker.strip(), text.strip()
        if len(text) < 10:
            continue
        turns.append(SpeakerTurn(
            speaker = speaker,
            role    = classify_speaker_role(speaker),
            section = "remarks",
            text    = text,
        ))
    qa_start = detect_qa_boundary(turns)
    for i, turn in enumerate(turns):
        turn.section = "qa" if i >= qa_start else "remarks"
    return turns

def group_sections(turns: list) -> dict[str, str]:
    fmt = lambda tl: "\n\n".join(f"{t.speaker}: {t.text}" for t in tl)
    cfg = TRANSCRIPT_SECTIONS
    sections = {}
    remarks = [t for t in turns if t.section == "remarks" and t.role != "operator"]
    cfo     = [t for t in turns if t.section == "remarks" and t.role == "cfo"]
    qa      = [t for t in turns if t.section == "qa"      and t.role != "operator"]
    all_    = [t for t in turns if t.role != "operator"]
    if remarks: sections["remarks"]    = fmt(remarks)[:cfg["remarks"].max_chars]
    if cfo:     sections["financials"] = fmt(cfo)[:cfg["financials"].max_chars]
    if qa:      sections["qa"]         = fmt(qa)[:cfg["qa"].max_chars]
    if all_:    sections["full"]       = fmt(all_)[:cfg["full"].max_chars]
    return sections

def is_press_release(content: str) -> bool:
    tl = content.lower()
    has_operator   = any(word in tl for word in ("operator:", "moderator:"))
    has_qa_section = any(phrase in tl for phrase in ("question-and-answer", "q&a session", "open for questions"))
    has_release    = any(phrase in tl for phrase in ("for immediate release", "press release", "reports first quarter", "reports second quarter", "reports third quarter", "reports fourth quarter", "financial results", "financial highlights"))
    return has_release and not (has_operator or has_qa_section)

def group_sections_press_release(content: str) -> dict[str, str]:
    cfg = TRANSCRIPT_SECTIONS
    return {
        "remarks": content[:cfg["remarks"].max_chars],
        "full":    content[:cfg["full"].max_chars],
    }

def build_section_body(
    ticker: str, period: str, section_key: str,
    section_text: str, signals: TranscriptSignals,
    is_press_release: bool = False,
) -> str:
    cfg   = TRANSCRIPT_SECTIONS[section_key]
    doc_type = "Earnings Press Release" if is_press_release else "Earnings Call"
    parts = []
    if signals.guidance_tone == "raised":     parts.append("Management raised guidance.")
    elif signals.guidance_tone == "lowered":  parts.append("Management lowered guidance.")
    elif signals.guidance_tone == "maintained":parts.append("Management reaffirmed guidance.")
    if signals.beat_miss == "beat":           parts.append("Results exceeded expectations.")
    elif signals.beat_miss == "miss":         parts.append("Results fell short of expectations.")
    if signals.positive_topics:
        parts.append(f"Positive themes: {', '.join(t.replace('_',' ') for t in sorted(signals.positive_topics))}.")
    if signals.negative_topics:
        parts.append(f"Headwinds: {', '.join(t.replace('_',' ') for t in sorted(signals.negative_topics))}.")
    if signals.macro_concerns:
        parts.append("Management cited macroeconomic headwinds.")

    header = f"{ticker} {doc_type} {period} — {cfg.name}. {' '.join(parts)} "
    return header + section_text

def fetch_transcripts_from_8k(ticker: str, n: int = 8) -> list[dict]:
    set_identity(SEC_ID)
    try:
        company = Company(ticker)
        filings = company.get_filings(form="8-K")
        results = []
        logger.info("[8-K] %s — scanning %d filings", ticker, len(filings))

        for filing in filings:
            if len(results) >= n: break
            try:
                attachments = filing.attachments
                exhibit = None
                for att in attachments:
                    if att.document_type in ("EX-99.1", "99.1", "EX-99", "99"):
                        exhibit = att
                        break

                if not exhibit:
                    try:
                        if hasattr(filing, "press_releases") and filing.press_releases:
                            exhibit = filing.press_releases[0]
                    except: pass
                if not exhibit: continue

                text = ""
                if hasattr(exhibit, "text"):
                    text = exhibit.text() if callable(exhibit.text) else exhibit.text
                text = text.strip() if text else ""
                if len(text) < 2000: continue

                text_lower = text[:2000].lower()
                if not any(kw in text_lower for kw in (
                    "earnings", "results", "revenue", "quarterly",
                    "net income", "per share", "eps", "quarter",
                )):
                    continue

                quarter, year = extract_period_from_text(text, filing.filing_date)
                results.append({
                    "symbol":  ticker,
                    "year":    year,
                    "quarter": quarter,
                    "date":    str(filing.filing_date),
                    "content": clean_exhibit_text(text),
                    "source":  "8k",
                })
            except Exception as e:
                logger.debug("[8-K] %s exhibit processing error: %s", ticker, e)
                continue

        logger.info("[8-K] %s → found %d earnings documents", ticker, len(results))
        return results
    except Exception as e:
        logger.error("[8-K] %s fetch failed: %s", ticker, e)
        return []

def fetch_latest_transcripts(ticker: str, n: int = 8) -> list[dict]:
    resp = requests.get(
        f"{FMP_BASE}/earning_call_transcript/{ticker}",
        params={"apikey": FMP_KEY},
        timeout=20,
    )
    if resp.status_code == 403:
        logger.error("[Transcript] 403 (Tier Restriction) - FMP Transcript API requires paid plan")
        return []
    if resp.status_code == 429:
        logger.warning("[Transcript] Rate limited, retrying in 60s")
        time.sleep(60)
        return fetch_latest_transcripts(ticker, n)
    resp.raise_for_status()
    data = resp.json()
    return data[:n] if isinstance(data, list) else []

def normalize_transcript(
    ticker:  str,
    year:    int,
    quarter: int,
    date:    str,
    content: str,
) -> list[FinancialDoc]:
    if not content.strip():
        return []
    period = f"Q{quarter} {year}"
    if not date:
        month = {1: "03", 2: "06", 3: "09", 4: "12"}[quarter]
        date  = f"{year}-{month}-01"

    press_release = is_press_release(content)
    if press_release:
        sections = group_sections_press_release(content)
    else:
        turns    = parse_transcript(content)
        sections = group_sections(turns)
        if not sections:
            logger.info("[Transcript] %s %s → No turns parsed, falling back to Press Release", ticker, period)
            sections = group_sections_press_release(content)
            press_release = True

    signals = extract_signals(content)
    regime  = classify_transcript_regime(signals)
    docs    = []
    for key, text in sections.items():
        if not text.strip(): continue
        cfg  = TRANSCRIPT_SECTIONS[key]
        body = build_section_body(ticker, period, key, text, signals, press_release)
        docs.append(FinancialDoc(
            source      = "transcript",
            entity      = ticker,
            entity_type = cfg.entity_type,
            date        = date,
            title       = f"{ticker} {'Press Release' if press_release else 'Earnings Call'} {period} — {cfg.name}",
            body        = body,
            tags        = list(cfg.tags) + [
                ticker.lower(),
                period.lower().replace(" ", "_"),
                "press_release" if press_release else "transcript",
            ],
            regime      = regime,
            meta        = {
                "period":           period,
                "quarter":          quarter,
                "year":             year,
                "section":          key,
                "source_type":      "press_release" if press_release else "transcript",
                "guidance_tone":    signals.guidance_tone,
                "beat_miss":        signals.beat_miss,
                "positive_topics":  list(signals.positive_topics),
                "negative_topics":  list(signals.negative_topics),
                "macro_concerns":   signals.macro_concerns,
                "char_count":       len(text),
            },
        ))
    return docs

def load_all_transcripts(
    tickers:             list[str],
    quarters_per_ticker: int = 8,
) -> list[FinancialDoc]:
    all_docs = []
    for ticker in tickers:
        if ticker in NO_TRANSCRIPT_TICKERS: continue
        try:
            raw_list = fetch_transcripts_from_8k(ticker, n=quarters_per_ticker)
            if not raw_list: continue
            for raw in raw_list:
                docs = normalize_transcript(
                    ticker  = raw.get("symbol", ticker),
                    year    = raw.get("year",    datetime.now().year),
                    quarter = raw.get("quarter", 1),
                    date    = raw.get("date",    "")[:10],
                    content = raw.get("content", ""),
                )
                all_docs.extend(docs)
            logger.info("[Transcript] %s successfully ingested (%d quarters)", ticker, len(raw_list))
            time.sleep(0.1)
        except Exception as e:
            logger.error("[Transcript] Critical failure for %s: %s", ticker, e)
    return all_docs