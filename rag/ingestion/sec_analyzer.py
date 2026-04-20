"""
SEC EDGAR Market Data Ingestion & Normalization
===============================================
Fetches company 10-K and 10-Q filings via edgartools and converts
them into FinancialDoc objects ready for chunking and embedding.
"""

import logging
from dataclasses import dataclass
from edgar import Company, set_identity

from .models import FinancialDoc
from .config import TICKER_REGISTRY

logger = logging.getLogger(__name__)

set_identity("antigravity@financialrag.com")



@dataclass
class SECSectionCfg:
    name: str
    entity_type: str
    max_chars: int
    tags: tuple

SEC_SECTIONS = {
    "business":          SECSectionCfg("Business Overview",       "sec_business", 20000, ("operations", "strategy")),
    "risk_factors":      SECSectionCfg("Risk Factors",            "sec_risk",     20000, ("risk", "compliance")),
    "mda":               SECSectionCfg("MD&A",                    "sec_mda",      20000, ("financials", "performance", "forward_looking")),
    "quantitative_risk": SECSectionCfg("Quantitative Mkt Risk",   "sec_mkt_risk", 15000, ("market_risk", "interest_rate")),
    "legal":             SECSectionCfg("Legal Proceedings",       "sec_legal",    10000, ("litigation", "legal")),
}

SECTION_REGIME_RULES = {
    "mda": {
        "restructuring":      ["layoffs", "restructuring", "cost reduction", "severance"],
        "expansion":          ["expansion", "acquisition", "merger", "new markets"],
        "supply_constraints": ["supply chain", "shortage", "logistics", "freight"],
    },
    "risk_factors": {
        "regulatory_risk":    ["antitrust", "regulatory", "probe", "investigation", "subpoena"],
        "macro_risk":         ["inflation", "interest rates", "recession", "geopolitical"],
    }
}


# Maps edgartools item keys to your section_key registry
ITEM_MAP = {
    "10-K": {
        "Item 1":   "business",
        "Item 1A":  "risk_factors",
        "Item 7":   "mda",
        "Item 7A":  "quantitative_risk",
        "Item 3":   "legal",
    },
    "10-Q": {
        "Part I, Item 2":   "mda",
        "Part I, Item 3":   "quantitative_risk",
        "Part II, Item 1":  "legal",
    },
}


def fetch_sections(ticker: str, form_type: str = "10-K") -> tuple[dict[str, str], dict]:
    company  = Company(ticker)
    filing   = company.get_filings(form=form_type).latest(1)
    if not filing:
        raise ValueError(f"No {form_type} filings found for {ticker}")
    doc      = filing.obj()
    meta     = {
        "accession_number": filing.accession_no,
        "filing_date":      str(filing.filing_date),
        "form_type":        form_type,
        "company_name":     company.name,
    }

    sections = {}
    item_map = ITEM_MAP.get(form_type, {})

    for item_key, section_key in item_map.items():
        try:
            item = doc[item_key]
            if item is None:
                continue
            text = item.text.strip() if hasattr(item, "text") else getattr(item, "strip", lambda: str(item))()
            if len(text) < 200:          # skip boilerplate cross-references
                continue
            max_chars = SEC_SECTIONS[section_key].max_chars
            sections[section_key] = text[:max_chars]
        except Exception:
            continue

    return sections, meta


def build_sec_body(ticker, company, form_type, fiscal_period, section_key, text) -> str:
    cfg = SEC_SECTIONS[section_key]
    return f"{company} ({ticker}) — {form_type} {cfg.name} — {fiscal_period}. {text}"


def classify_sec_regime(section_key: str, text: str) -> str:
    rules      = SECTION_REGIME_RULES.get(section_key, {})
    text_lower = text.lower()
    for regime_label, keywords in rules.items():
        if any(kw in text_lower for kw in keywords):
            return regime_label
    return "unclassified"


def normalize_sec(ticker: str, form_type: str = "10-K") -> list[FinancialDoc]:
    sections, meta   = fetch_sections(ticker, form_type)
    company          = meta["company_name"]
    fiscal_period    = meta["filing_date"][:7] # YYYY-MM
    docs             = []

    for section_key, text in sections.items():
        cfg  = SEC_SECTIONS[section_key]
        body = build_sec_body(ticker, company, form_type, fiscal_period, section_key, text)

        docs.append(FinancialDoc(
            source      = "sec",
            entity      = ticker,
            entity_type = cfg.entity_type,
            date        = meta["filing_date"],
            title       = f"{company} {form_type} — {cfg.name} ({fiscal_period})",
            body        = body,
            tags        = list(cfg.tags) + [form_type.lower(), ticker.lower()],
            regime      = classify_sec_regime(section_key, text),
            meta        = {
                "form_type":        form_type,
                "accession_number": meta["accession_number"],
                "fiscal_period":    fiscal_period,
                "section":          section_key,
                "char_count":       len(text),
                "truncated":        len(text) == cfg.max_chars,
            },
        ))

    return docs


def load_all_sec(tickers: list[str]) -> list[FinancialDoc]:

    all_docs = []
    for ticker in tickers:
        for form_type in ["10-K", "10-Q"]:
            try:
                docs = normalize_sec(ticker, form_type)
                all_docs.extend(docs)
                logger.info("[SEC] %s %s parsed successfully", ticker, form_type)
            except Exception as e:
                logger.error("[SEC] %s %s failed: %s", ticker, form_type, e)
    return all_docs
