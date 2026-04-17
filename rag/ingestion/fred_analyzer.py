"""
FRED Macro-Economic Data Ingestion Pipeline
===========================================
Fetches raw numerical time-series from FRED and synthesizes the full historical data 
into a current "State of the World" narrative for LLM RAG indexing. 

Pipeline Stages:
1. Fetching: Downloads the entire timeline to enable multi-decade statistical context.
2. Analysis: Computes historical averages, standard deviations, and accurate YoY changes.
3. NLP Generation: Synthesizes dense natural language sentences mapping math to text.
4. Normalization: Packages the final narrative into a unified FinancialDoc interface.
"""

import os
import statistics
import logging
import requests
from pathlib import Path

from dotenv import load_dotenv
from .models import FinancialDoc

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

logger = logging.getLogger(__name__)

FRED_API_KEY = os.getenv("FRED_API_KEY")
FRED_BASE    = "https://api.stlouisfed.org/fred"

FRED_ENTITY_TYPES = {
    "GDP":        "macro",    # Total US economic output
    "CPIAUCSL":   "macro",    # Consumer price inflation
    "UNRATE":     "macro",    # Unemployment rate
    "FEDFUNDS":   "rate",     # Federal funds overnight rate
    "GS10":       "rate",     # 10-Year Treasury yield (monthly)
    "T10YIE":     "rate",     # Market-implied 10-year inflation expectations
    "NASDAQCOM":  "index",    # NASDAQ Composite — market sentiment
}

SERIES_META = {
    "GDP":        {"name": "US GDP",                         "unit": "billions of USD", "direction": "higher_is_better"},
    "CPIAUCSL":   {"name": "CPI inflation",                  "unit": "index",           "direction": "neutral"},
    "UNRATE":     {"name": "unemployment rate",              "unit": "%",               "direction": "lower_is_better"},
    "FEDFUNDS":   {"name": "federal funds rate",             "unit": "%",               "direction": "neutral"},
    "GS10":       {"name": "10-year Treasury yield",         "unit": "%",               "direction": "neutral"},
    "T10YIE":     {"name": "10-year inflation expectations", "unit": "%",               "direction": "neutral"},
    "NASDAQCOM":  {"name": "NASDAQ Composite",               "unit": "points",          "direction": "higher_is_better"},
}


def fetch_fred(series_id: str) -> list[dict]:
    resp = requests.get(
        f"{FRED_BASE}/series/observations",
        params={
            "series_id": series_id,
            "api_key": FRED_API_KEY,
            "file_type": "json",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("observations", [])



def analyze_fred(series_id: str, observations: list[dict]) -> dict:
    valid_observations = [
        {"date": obs["date"], "value": float(obs["value"])}
        for obs in observations
        if obs.get("value") not in (".", None, "")
    ]
    if not valid_observations:
        raise ValueError(f"No valid observations for {series_id}")

    values   = [obs["value"] for obs in valid_observations]
    latest   = valid_observations[-1]
    prev     = valid_observations[-2]   if len(valid_observations) >= 2  else None
    
    from datetime import datetime
    latest_date = datetime.strptime(latest["date"], "%Y-%m-%d").date()
    
    year_ago = None
    for obs in reversed(valid_observations[:-1]):
        obs_date = datetime.strptime(obs["date"], "%Y-%m-%d").date()
        days_diff = (latest_date - obs_date).days
        if days_diff >= 365:
            year_ago = obs
            break

    return {
        "series_id":                     series_id,
        "meta":                          SERIES_META[series_id],
        "latest":                        latest,
        "prev":                          prev,
        "year_ago":                      year_ago,
        "change_short_term":             latest["value"] - prev["value"]       if prev      else None,
        "change_year_over_year":         latest["value"] - year_ago["value"]   if year_ago  else None,
        "percent_change_year_over_year": ((latest["value"] - year_ago["value"])
                                          / abs(year_ago["value"])) * 100      if year_ago  else None,
        "mean":                          statistics.mean(values),
        "stdev":                         statistics.stdev(values) if len(values) > 1 else 0.0,
        "period_high":                   max(values),
        "period_low":                    min(values),
        "observation_count":             len(valid_observations),
    }



def direction_verb(change: float, direction: str) -> str:
    if direction == "higher_is_better":
        return "rose"  if change > 0 else "fell"
    if direction == "lower_is_better":
        return "fell"  if change > 0 else "rose"
    return "rose"      if change > 0 else "fell"



def build_body(stats: dict) -> str:
    meta      = stats["meta"]
    name      = meta["name"]
    unit      = meta["unit"]
    direction = meta["direction"]
    latest    = stats["latest"]
    sentences = []

    sentences.append(
        f"The {name} was {latest['value']:,.2f} {unit} as of {latest['date']}."
    )

    if stats["change_short_term"] is not None:
        verb = direction_verb(stats["change_short_term"], direction)
        sign = "+" if stats["change_short_term"] > 0 else ""
        sentences.append(
            f"The {name} {verb} by {sign}{stats['change_short_term']:.2f} {unit} "
            f"from the prior period ({stats['prev']['date']})."
        )

    if stats["change_year_over_year"] is not None:
        sign     = "+" if stats["change_year_over_year"] > 0 else ""
        pct_sign = "+" if stats["percent_change_year_over_year"] > 0 else ""
        sentences.append(
            f"Compared to a year ago ({stats['year_ago']['date']}), "
            f"the {name} has moved {sign}{stats['change_year_over_year']:.2f} {unit} "
            f"({pct_sign}{stats['percent_change_year_over_year']:.1f}%)."
        )

    diff = stats["latest"]["value"] - stats["mean"]
    rel  = "above" if diff > 0 else "below"
    sentences.append(
        f"The current {name} reading sits {abs(diff):,.2f} {unit} "
        f"{rel} its historical average of {stats['mean']:,.2f}."
    )

    if stats["stdev"] > 0:
        z = (stats["latest"]["value"] - stats["mean"]) / stats["stdev"]
        if abs(z) > 2:
            extreme = "high" if z > 0 else "low"
            sentences.append(
                f"At {abs(z):.1f} standard deviations from the mean, "
                f"this {name} reading is unusually {extreme} historically."
            )

    return " ".join(sentences)



def normalize_fred(series_id: str, raw: list[dict]) -> "FinancialDoc":
    stats = analyze_fred(series_id, raw)
    body  = build_body(stats)
    meta  = stats["meta"]

    return FinancialDoc(
        source      = "fred",
        entity      = series_id,
        entity_type = FRED_ENTITY_TYPES[series_id],
        date        = stats["latest"]["date"],
        title       = f"{meta['name']} — {stats['latest']['date']}",
        body        = body,
        meta        = {
            "unit":                          meta["unit"],
            "latest_value":                  stats["latest"]["value"],
            "change_short_term":             stats["change_short_term"],
            "change_year_over_year":         stats["change_year_over_year"],
            "percent_change_year_over_year": stats["percent_change_year_over_year"],
            "mean":                          stats["mean"],
            "stdev":                         stats["stdev"],
            "period_high":                   stats["period_high"],
            "period_low":                    stats["period_low"],
            "observation_count":             stats["observation_count"],
        },
    )



def load_all_fred() -> list["FinancialDoc"]:
    docs = []
    for series_id in FRED_ENTITY_TYPES:
        try:
            raw = fetch_fred(series_id)
            doc = normalize_fred(series_id, raw)
            docs.append(doc)
        except Exception as e:
            raise RuntimeError(f"Error processing {series_id}: {str(e)}") from e
    return docs
