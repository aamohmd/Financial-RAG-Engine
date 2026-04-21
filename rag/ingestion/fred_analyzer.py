"""
FRED Macro-Economic Data Ingestion Pipeline
===========================================
Fetches raw numerical time-series from FRED and synthesizes the full historical data
into a current "State of the World" narrative for LLM RAG indexing.

Pipeline Stages:
1. Fetching:      Downloads the entire timeline to enable multi-decade statistical context.
2. Analysis:      Computes rolling 10-year averages, standard deviations, and YoY changes.
3. NLP Generation: Synthesizes dense natural language sentences mapping math to text.
4. Normalization: Packages the final narrative into a unified FinancialDoc interface.
"""

import os
import logging
import time
import requests
import statistics
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv

from .models import FinancialDoc

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

logger       = logging.getLogger(__name__)
FRED_API_KEY = os.getenv("FRED_API_KEY")
FRED_BASE    = "https://api.stlouisfed.org/fred"


FRED_ENTITY_TYPES = {
    "GDP":             "macro",
    "A191RL1Q225SBEA": "macro",
    "DPCERL1Q225SBEA": "macro",
    "A006RL1Q225SBEA": "macro",
    "PI":              "macro",
    "PCE":             "macro",
    "PSAVERT":         "macro",
    "CP":              "macro",
    "CPIAUCSL":        "macro",
    "UNRATE":          "macro",
    "FEDFUNDS":        "rate",
    "GS10":            "rate",
    "T10YIE":          "rate",
    "NASDAQCOM":       "index",
}

SERIES_META = {
    "GDP":             {"name": "US GDP",                         "unit": "billions of USD", "direction": "higher_is_better"},
    "A191RL1Q225SBEA": {"name": "Real GDP growth rate",           "unit": "%",               "direction": "higher_is_better"},
    "DPCERL1Q225SBEA": {"name": "Real PCE growth rate",           "unit": "%",               "direction": "higher_is_better"},
    "A006RL1Q225SBEA": {"name": "Real Investment growth rate",    "unit": "%",               "direction": "higher_is_better"},
    "PI":              {"name": "Personal income",                "unit": "billions of USD", "direction": "higher_is_better"},
    "PCE":             {"name": "Personal consumption",           "unit": "billions of USD", "direction": "higher_is_better"},
    "PSAVERT":         {"name": "Personal saving rate",           "unit": "%",               "direction": "neutral"},
    "CP":              {"name": "Corporate profits",              "unit": "billions of USD", "direction": "higher_is_better"},
    "CPIAUCSL":        {"name": "CPI inflation",                  "unit": "index points",    "direction": "neutral"},
    "UNRATE":          {"name": "unemployment rate",              "unit": "%",               "direction": "lower_is_better"},
    "FEDFUNDS":        {"name": "federal funds rate",             "unit": "%",               "direction": "neutral"},
    "GS10":            {"name": "10-year Treasury yield",         "unit": "%",               "direction": "neutral"},
    "T10YIE":          {"name": "10-year inflation expectations", "unit": "%",               "direction": "neutral"},
    "NASDAQCOM":       {"name": "NASDAQ Composite",               "unit": "points",          "direction": "higher_is_better"},
}

class RegimeSignals:
    __slots__ = ("value", "pct_yoy")

    def __init__(self, value: float, pct_yoy: float | None):
        self.value   = value
        self.pct_yoy = pct_yoy



Z_THRESHOLDS = {
    "GDP":             999,
    "A191RL1Q225SBEA": 999,
    "DPCERL1Q225SBEA": 999,
    "A006RL1Q225SBEA": 999,
    "PI":              999,
    "PCE":             999,
    "CP":              999,
    "PSAVERT":         2.0,
    "NASDAQCOM":       999,
    "CPIAUCSL":        999,
    "FEDFUNDS":        2.0,
    "GS10":            2.0,
    "T10YIE":          2.0,
    "UNRATE":          2.0,
}


FRED_REGIME_RULES: dict[str, dict[str, callable]] = {

    "A191RL1Q225SBEA": {
        "strong_growth":   lambda s: s.value >  3.0,
        "moderate_growth": lambda s: 1.0 <= s.value <= 3.0,
        "stagnation":      lambda s: 0.0 <= s.value <  1.0,
        "contraction":     lambda s: s.value <  0.0,
    },

    "DPCERL1Q225SBEA": {
        "strong_consumption":        lambda s: s.value >  3.0,
        "moderate_consumption":      lambda s: 0.0 <= s.value <= 3.0,
        "consumption_contraction":   lambda s: s.value <  0.0,
    },

    "A006RL1Q225SBEA": {
        "investment_expansion":      lambda s: s.value >  5.0,
        "moderate_investment":       lambda s: 0.0 <= s.value <= 5.0,
        "investment_contraction":    lambda s: s.value <  0.0,
    },

    "GDP": {
        "strong_growth":   lambda s: s.pct_yoy is not None and s.pct_yoy >  5.0,
        "moderate_growth": lambda s: s.pct_yoy is not None and 2.0 <= s.pct_yoy <= 5.0,
        "stagnation":      lambda s: s.pct_yoy is not None and 0.0 <= s.pct_yoy <  2.0,
        "contraction":     lambda s: s.pct_yoy is not None and s.pct_yoy <  0.0,
    },

    "PI": {
        "strong_income_growth":    lambda s: s.pct_yoy is not None and s.pct_yoy >  4.0,
        "moderate_income_growth":  lambda s: s.pct_yoy is not None and 0.0 <= s.pct_yoy <= 4.0,
        "income_contraction":      lambda s: s.pct_yoy is not None and s.pct_yoy <  0.0,
    },

    "PCE": {
        "strong_consumption":       lambda s: s.pct_yoy is not None and s.pct_yoy >  5.0,
        "moderate_consumption":     lambda s: s.pct_yoy is not None and 1.0 <= s.pct_yoy <= 5.0,
        "weak_consumption":         lambda s: s.pct_yoy is not None and s.pct_yoy <  1.0,
    },

    "CP": {
        "profit_expansion":    lambda s: s.pct_yoy is not None and s.pct_yoy >  5.0,
        "stable_profits":      lambda s: s.pct_yoy is not None and 0.0 <= s.pct_yoy <= 5.0,
        "profit_contraction":  lambda s: s.pct_yoy is not None and s.pct_yoy <  0.0,
    },

    "CPIAUCSL": {
        "high_inflation":      lambda s: s.pct_yoy is not None and s.pct_yoy >  4.0,
        "elevated_inflation":  lambda s: s.pct_yoy is not None and 2.0 < s.pct_yoy <= 4.0,
        "stable_prices":       lambda s: s.pct_yoy is not None and 0.0 <= s.pct_yoy <= 2.0,
        "deflation":           lambda s: s.pct_yoy is not None and s.pct_yoy <  0.0,
    },

    "UNRATE": {
        "full_employment":  lambda s: s.value <  4.5,
        "tight_labor":      lambda s: 4.5 <= s.value <= 6.0,
        "slack_labor":      lambda s: s.value >  6.0,
    },

    "FEDFUNDS": {
        "restrictive":    lambda s: s.value >  4.0,
        "neutral":        lambda s: 2.0 <= s.value <= 4.0,
        "accommodative":  lambda s: s.value <  2.0,
    },

    "GS10": {
        "high_yield_environment":  lambda s: s.value >  4.5,
        "neutral_yield":           lambda s: 2.0 <= s.value <= 4.5,
        "low_yield_environment":   lambda s: s.value <  2.0,
    },

    "T10YIE": {
        "elevated_expectations":  lambda s: s.value >  3.0,
        "moderate_expectations":  lambda s: 1.5 <= s.value <= 3.0,
        "anchored_expectations":  lambda s: s.value <  1.5,
    },

    "NASDAQCOM": {
        "bull_market":     lambda s: s.pct_yoy is not None and s.pct_yoy >  20.0,
        "neutral_market":  lambda s: s.pct_yoy is not None and -10.0 <= s.pct_yoy <= 20.0,
        "bear_market":     lambda s: s.pct_yoy is not None and s.pct_yoy < -10.0,
    },

    "PSAVERT": {
        "elevated_savings": lambda s: s.value >  8.0,
        "normal_savings":   lambda s: 4.0 <= s.value <= 8.0,
        "low_savings":      lambda s: s.value <  4.0,
    },
}


def fetch_fred(series_id: str) -> list[dict]:
    session = requests.Session()
    # Retry on 500, 502, 503, 504
    retries = requests.adapters.Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504]
    )
    session.mount("https://", requests.adapters.HTTPAdapter(max_retries=retries))
    
    resp = session.get(
        f"{FRED_BASE}/series/observations",
        params={
            "series_id": series_id,
            "api_key":   FRED_API_KEY,
            "file_type": "json",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("observations", [])


def rolling_stats(valid_observations: list[dict], years: int = 10) -> tuple[float, float]:
    if not valid_observations:
        return 0.0, 0.0
    cutoff = (
        datetime.strptime(valid_observations[-1]["date"], "%Y-%m-%d").date()
        - timedelta(days=years * 365)
    )
    window = [
        obs["value"] for obs in valid_observations
        if datetime.strptime(obs["date"], "%Y-%m-%d").date() >= cutoff
    ]
    if len(window) < 2:
        window = [obs["value"] for obs in valid_observations]
    return statistics.mean(window), statistics.stdev(window) if len(window) > 1 else 0.0


def analyze_fred(series_id: str, observations: list[dict]) -> dict:
    valid_observations = [
        {"date": obs["date"], "value": float(obs["value"])}
        for obs in observations
        if obs.get("value") not in (".", None, "")
    ]
    if not valid_observations:
        raise ValueError(f"No valid observations for {series_id}")

    values      = [obs["value"] for obs in valid_observations]
    latest      = valid_observations[-1]
    prev        = valid_observations[-2] if len(valid_observations) >= 2 else None
    latest_date = datetime.strptime(latest["date"], "%Y-%m-%d").date()

    year_ago = None
    for obs in reversed(valid_observations[:-1]):
        if (latest_date - datetime.strptime(obs["date"], "%Y-%m-%d").date()).days >= 365:
            year_ago = obs
            break

    mean_val, stdev_val = rolling_stats(valid_observations, years=10)

    change_yoy  = (latest["value"] - year_ago["value"]) if year_ago else None
    pct_yoy     = (change_yoy / abs(year_ago["value"]) * 100) if (
                    change_yoy is not None and year_ago and year_ago["value"] != 0
                  ) else None

    return {
        "series_id":                     series_id,
        "meta":                          SERIES_META[series_id],
        "latest":                        latest,
        "prev":                          prev,
        "year_ago":                      year_ago,
        "change_short_term":             (latest["value"] - prev["value"]) if prev else None,
        "change_year_over_year":         change_yoy,
        "percent_change_year_over_year": pct_yoy,
        "mean":                          mean_val,
        "stdev":                         stdev_val,
        "period_high":                   max(values),
        "period_low":                    min(values),
        "observation_count":             len(valid_observations),
    }


def direction_verb(change: float) -> str:
    if change > 0:  return "rose"
    if change < 0:  return "fell"
    return "was unchanged"


def build_body(stats: dict) -> str:
    meta    = stats["meta"]
    name    = meta["name"]
    unit    = meta["unit"]
    latest  = stats["latest"]
    sentences = []

    if stats["series_id"] == "CPIAUCSL" and stats["percent_change_year_over_year"] is not None:
        sentences.append(
            f"Consumer prices rose {stats['percent_change_year_over_year']:.1f}% "
            f"year-over-year as of {latest['date']}, "
            f"based on a CPI index level of {latest['value']:,.2f}."
        )
    else:
        sentences.append(
            f"The {name} was {latest['value']:,.2f} {unit} as of {latest['date']}."
        )

    if stats["change_short_term"] is not None:
        change = stats["change_short_term"]
        if abs(change) < 1e-9:
            sentences.append(
                f"The {name} was unchanged from the prior period ({stats['prev']['date']})."
            )
        else:
            verb = direction_verb(change)
            sign = "+" if change > 0 else ""
            sentences.append(
                f"The {name} {verb} by {sign}{change:.2f} {unit} "
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

    diff = latest["value"] - stats["mean"]
    rel  = "above" if diff > 0 else "below"
    sentences.append(
        f"The current {name} reading sits {abs(diff):,.2f} {unit} "
        f"{rel} its historical average of {stats['mean']:,.2f}."
    )

    threshold = Z_THRESHOLDS.get(stats["series_id"], 2.0)
    if stats["stdev"] > 0:
        z = (latest["value"] - stats["mean"]) / stats["stdev"]
        if abs(z) > threshold:
            extreme = "high" if z > 0 else "low"
            sentences.append(
                f"At {abs(z):.1f} standard deviations from its 10-year mean, "
                f"the {name} is at an unusually {extreme} level."
            )

    return " ".join(sentences)


def classify_fred_regime(series_id: str, value: float, pct_yoy: float | None) -> str:
    rules   = FRED_REGIME_RULES.get(series_id, {})
    signals = RegimeSignals(value=value, pct_yoy=pct_yoy)
    for regime_label, condition in rules.items():
        try:
            if condition(signals):
                return regime_label
        except Exception:
            continue
    return "unclassified"


def normalize_fred(series_id: str, raw: list[dict]) -> FinancialDoc:
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
        tags        = ["macro", "fred", series_id.lower()],
        regime      = classify_fred_regime(
                          series_id,
                          stats["latest"]["value"],
                          stats["percent_change_year_over_year"],
                      ),
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


def load_all_fred() -> list[FinancialDoc]:
    docs = []
    for series_id in FRED_ENTITY_TYPES:
        try:
            raw = fetch_fred(series_id)
            doc = normalize_fred(series_id, raw)
            docs.append(doc)
            logger.info("[FRED] %s → regime: %s", doc.title, doc.regime)
            time.sleep(0.5)
        except Exception as e:
            logger.error("[FRED] %s failed: %s", series_id, e)
    return docs