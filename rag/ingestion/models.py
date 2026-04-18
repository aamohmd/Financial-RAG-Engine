"""
Shared data models used across all ingestion sources.
"""

from dataclasses import dataclass, field


@dataclass
class FinancialDoc:
    """
    Normalized container — every data source maps to this before chunking.

    One FinancialDoc represents one logical document (e.g. one FRED series,
    one SEC filing, one earnings transcript). Its `body` is natural-language
    text that gets split into Chunks by the sentence-window chunker.
    """
    source:      str      # "fred" | "bea" | "sec" | "yfinance" | "earnings"
    entity:      str      # "GDP" | "CPIAUCSL" | "AAPL" — what the data is about
    entity_type: str      # "macro" | "equity" | "rate" | "index"
    date:        str      # ISO format YYYY-MM-DD (latest data point)
    title:       str
    body:        str      # natural-language text, ready for chunking
    tags:        list[str] = field(default_factory=list)
    regime:      str = "unclassified"
    meta:        dict = field(default_factory=dict)
