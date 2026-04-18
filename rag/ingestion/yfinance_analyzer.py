"""
yFinance Market Data Ingestion & Normalization
==============================================
Fetches company fundamentals and market data via yfinance and converts
them into FinancialDoc objects ready for chunking and embedding.

One ticker produces up to 5 FinancialDoc objects:
    equity_profile   — company overview and valuation multiples
    equity_income    — income statement (revenue, margins, EPS)
    equity_balance   — balance sheet (assets, debt, equity)
    equity_cashflow  — cash flow (operating CF, capex, FCF)
    equity_price     — price momentum and technicals summary
"""

import time
import logging
import yfinance as yf
import pandas as pd
from datetime import datetime
from .models import FinancialDoc

logger = logging.getLogger(__name__)




from .config import TICKER_REGISTRY

YFINANCE_SUBTYPES = {
    "profile":  "equity_profile",
    "income":   "equity_income",
    "balance":  "equity_balance",
    "cashflow": "equity_cashflow",
    "price":    "equity_price",
}

INCOME_KEYS = [
    "Total Revenue", "Gross Profit", "Operating Income",
    "EBITDA", "Net Income", "Basic EPS", "Diluted EPS",
]
BALANCE_KEYS = [
    "Total Assets", "Total Liabilities Net Minority Interest",
    "Stockholders Equity", "Cash And Cash Equivalents",
    "Total Debt", "Net Debt",
]
CASHFLOW_KEYS = [
    "Operating Cash Flow", "Capital Expenditure",
    "Free Cash Flow", "Issuance Of Debt", "Repurchase Of Capital Stock",
]



def fetch_yfinance(ticker: str) -> yf.Ticker:
    return yf.Ticker(ticker)



def safe_info(ticker_obj: yf.Ticker) -> dict:
    try:
        return ticker_obj.info or {}
    except Exception:
        return {}

def safe_df(df) -> pd.DataFrame | None:
    if df is None or df.empty:
        return None
    df = df.dropna(how="all")
    return df[sorted(df.columns, reverse=True)]   # newest period first

def get_value(df: pd.DataFrame, row_key: str, col_idx: int = 0) -> float | None:
    for idx in df.index:
        if row_key.lower() in str(idx).lower():
            val = df.iloc[df.index.get_loc(idx), col_idx]
            if pd.notna(val) and val != 0:
                return float(val)
    return None

def period_label(df: pd.DataFrame, col_idx: int = 0) -> str:
    try:
        return pd.Timestamp(df.columns[col_idx]).strftime("%Y-%m-%d")
    except Exception:
        return "unknown"



def fmt(val: float | None, unit: str = "B") -> str:
    if val is None:
        return "N/A"
    divisor = 1e9 if unit == "B" else 1e6
    return f"${val / divisor:,.2f}B" if unit == "B" else f"${val / divisor:,.2f}M"

def pct_change(current: float | None, prior: float | None) -> str | None:
    if current is None or prior is None or prior == 0:
        return None
    pct  = ((current - prior) / abs(prior)) * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


def analyze_profile(info: dict) -> tuple[str, dict, str]:
    ticker   = info.get("symbol", "")
    name     = info.get("longName") or info.get("shortName") or ticker
    sector   = info.get("sector",   "unknown sector")
    industry = info.get("industry", "unknown industry")

    market_cap   = info.get("marketCap")
    trailing_pe  = info.get("trailingPE")
    forward_pe   = info.get("forwardPE")
    pb_ratio     = info.get("priceToBook")
    ps_ratio     = info.get("priceToSalesTrailingTwelveMonths")
    trailing_eps = info.get("trailingEps")
    forward_eps  = info.get("forwardEps")
    div_yield    = info.get("dividendYield")
    short_ratio  = info.get("shortRatio")
    rec_key      = info.get("recommendationKey", "")
    rec_mean     = info.get("recommendationMean")

    sentences = []

    cap_str = f"${market_cap / 1e9:.1f}B" if market_cap else "an undisclosed market cap"
    sentences.append(
        f"{name} ({ticker}) is a {industry} company in the {sector} sector "
        f"with a market capitalization of {cap_str}."
    )

    valuation_parts = []
    if trailing_pe: valuation_parts.append(f"a trailing P/E of {trailing_pe:.1f}x")
    if forward_pe:  valuation_parts.append(f"a forward P/E of {forward_pe:.1f}x")
    if pb_ratio:    valuation_parts.append(f"a price-to-book of {pb_ratio:.2f}x")
    if ps_ratio:    valuation_parts.append(f"a price-to-sales of {ps_ratio:.2f}x")
    if valuation_parts:
        sentences.append(f"{name} trades at {', '.join(valuation_parts)}.")

    eps_parts = []
    if trailing_eps: eps_parts.append(f"trailing EPS of ${trailing_eps:.2f}")
    if forward_eps:  eps_parts.append(f"forward EPS of ${forward_eps:.2f}")
    if eps_parts:
        sentences.append(f"{name} has a {' and '.join(eps_parts)}.")

    if div_yield:
        sentences.append(f"{name} pays a dividend yield of {div_yield * 100:.2f}%.")

    if rec_key:
        rec_str = f" (mean score {rec_mean:.1f}/5.0)" if rec_mean else ""
        sentences.append(
            f"The analyst consensus rating for {name} is '{rec_key}'{rec_str}."
        )

    if short_ratio:
        sentences.append(
            f"{name} has a short ratio of {short_ratio:.1f} days to cover."
        )

    meta = {
        "market_cap":   market_cap,
        "trailing_pe":  trailing_pe,
        "forward_pe":   forward_pe,
        "pb_ratio":     pb_ratio,
        "ps_ratio":     ps_ratio,
        "trailing_eps": trailing_eps,
        "forward_eps":  forward_eps,
        "div_yield":    div_yield,
        "sector":       sector,
        "industry":     industry,
        "rec_key":      rec_key,
    }
    return " ".join(sentences), meta, datetime.today().strftime("%Y-%m-%d")


def analyze_statement(
    ticker: str,
    name:   str,
    df:     pd.DataFrame | None,
    keys:   list[str],
    subtype: str,
    period:  str = "annual",
) -> tuple[str, dict, str]:

    if df is None:
        return f"No {subtype} data available for {name} ({ticker}).", {}, "unknown"

    date  = period_label(df, 0)
    prior = period_label(df, 1) if df.shape[1] >= 2 else None
    sentences = []
    meta_vals = {}

    period_str = "fiscal year" if period == "annual" else "fiscal quarter"
    sentences.append(
        f"{name} ({ticker}) {subtype} for the {period_str} ended {date}:"
    )

    for key in keys:
        current = get_value(df, key, 0)
        prev    = get_value(df, key, 1) if prior else None
        if current is None:
            continue

        chg     = pct_change(current, prev)
        chg_str = f", {chg} year-over-year" if chg else ""
        label   = key.replace("Net Minority Interest", "").replace(" Reported", "").strip()
        sentences.append(f"{name}'s {label} was {fmt(current, 'B')}{chg_str}.")
        meta_vals[key.lower().replace(" ", "_")] = current

    # Derived metrics
    if subtype == "income":
        rev = get_value(df, "Total Revenue", 0)
        gp  = get_value(df, "Gross Profit",  0)
        ni  = get_value(df, "Net Income",    0)
        if rev and gp:
            gm = (gp / rev) * 100
            sentences.append(f"{name}'s gross margin was {gm:.1f}%.")
            meta_vals["gross_margin_pct"] = gm
        if rev and ni:
            npm = (ni / rev) * 100
            sentences.append(f"{name}'s net profit margin was {npm:.1f}%.")
            meta_vals["net_margin_pct"] = npm

    if subtype == "cashflow":
        op_cf = get_value(df, "Operating Cash Flow", 0)
        capex = get_value(df, "Capital Expenditure",  0)
        if op_cf and capex:
            fcf = op_cf + capex   # capex is negative in yfinance
            sentences.append(
                f"{name}'s free cash flow was {fmt(fcf, 'B')} "
                f"({fmt(op_cf, 'B')} operating cash flow minus {fmt(abs(capex), 'B')} capex)."
            )
            meta_vals["free_cash_flow"] = fcf

    return " ".join(sentences), meta_vals, date


def analyze_price(
    ticker: str,
    name:   str,
    info:   dict,
) -> tuple[str, dict, str]:

    current_price = info.get("currentPrice") or info.get("regularMarketPrice")
    high_52w      = info.get("fiftyTwoWeekHigh")
    low_52w       = info.get("fiftyTwoWeekLow")
    ma_50         = info.get("fiftyDayAverage")
    ma_200        = info.get("twoHundredDayAverage")
    beta          = info.get("beta")

    sentences = []

    if current_price:
        sentences.append(f"{name} ({ticker}) last traded at ${current_price:,.2f}.")

    if high_52w and low_52w and current_price:
        pct_from_high = ((current_price - high_52w) / high_52w) * 100
        pct_from_low  = ((current_price - low_52w)  / low_52w)  * 100
        sentences.append(
            f"{name} is {abs(pct_from_high):.1f}% below its 52-week high of "
            f"${high_52w:,.2f} and {pct_from_low:.1f}% above its 52-week low of ${low_52w:,.2f}."
        )

    if ma_50 and ma_200 and current_price:
        above_below = "above" if current_price > ma_200 else "below"
        cross_type  = "golden" if ma_50 > ma_200 else "death"
        sentences.append(
            f"{name} is trading {above_below} its 200-day moving average (${ma_200:,.2f}), "
            f"with its 50-day average (${ma_50:,.2f}) forming a {cross_type} cross signal."
        )

    if beta:
        sensitivity = "high" if beta > 1.3 else ("low" if beta < 0.7 else "moderate")
        sentences.append(
            f"{name} has a beta of {beta:.2f}, indicating {sensitivity} "
            f"sensitivity to broad market movements."
        )

    pct_from_high = ((current_price - high_52w) / high_52w * 100) if (current_price and high_52w) else None

    meta = {
        "current_price":      current_price,
        "high_52w":           high_52w,
        "low_52w":            low_52w,
        "ma_50":              ma_50,
        "ma_200":             ma_200,
        "beta":               beta,
        "pct_from_52w_high":  pct_from_high,
    }
    return " ".join(sentences), meta, datetime.today().strftime("%Y-%m-%d")



def classify_equity_regime(subtype: str, meta: dict, info: dict) -> str:
    if subtype == "profile":
        pe = info.get("trailingPE")
        if pe is None: return "unclassified"
        if pe > 40:    return "growth_premium"
        if pe > 25:    return "fairly_valued"
        if pe > 0:     return "value"
        return "unprofitable"

    if subtype == "income":
        margin = meta.get("net_margin_pct")
        if margin is None: return "unclassified"
        if margin > 20:    return "high_margin"
        if margin > 10:    return "moderate_margin"
        if margin > 0:     return "thin_margin"
        return "unprofitable"

    if subtype == "balance":
        assets = meta.get("total_assets")
        debt   = meta.get("total_debt")
        if assets and debt:
            leverage = debt / assets
            if leverage > 0.6: return "highly_leveraged"
            if leverage > 0.3: return "moderate_leverage"
            return "low_leverage"
        return "unclassified"

    if subtype == "cashflow":
        fcf = meta.get("free_cash_flow")
        if fcf is None: return "unclassified"
        return "cash_generative" if fcf > 0 else "cash_consuming"

    if subtype == "price":
        pct  = meta.get("pct_from_52w_high")
        ma50  = meta.get("ma_50")
        ma200 = meta.get("ma_200")
        if pct is None: return "unclassified"
        if pct > -5:    return "near_52w_high"
        if pct < -20:
            return "bear_territory" if (ma50 and ma200 and ma50 < ma200) else "pullback"
        return "uptrend" if (ma50 and ma200 and ma50 > ma200) else "neutral_trend"

    return "unclassified"



def normalize_yfinance(ticker: str, ticker_obj: yf.Ticker) -> list[FinancialDoc]:
    info = safe_info(ticker_obj)
    name = info.get("longName") or info.get("shortName") or ticker
    docs = []

    # Profile
    body, meta, date = analyze_profile(info)
    docs.append(FinancialDoc(
        source      = "yfinance",
        entity      = ticker,
        entity_type = "equity_profile",
        date        = date,
        title       = f"{name} — Company Profile",
        body        = body,
        tags        = ["equity", "profile", "valuation", info.get("sector", "").lower()],
        regime      = classify_equity_regime("profile", meta, info),
        meta        = meta,
    ))

    # Income statement
    body, meta, date = analyze_statement(
        ticker, name, safe_df(ticker_obj.financials), INCOME_KEYS, "income"
    )
    docs.append(FinancialDoc(
        source      = "yfinance",
        entity      = ticker,
        entity_type = "equity_income",
        date        = date,
        title       = f"{name} — Income Statement {date}",
        body        = body,
        tags        = ["equity", "income", "revenue", "earnings", "margins"],
        regime      = classify_equity_regime("income", meta, info),
        meta        = meta,
    ))

    # Balance sheet
    body, meta, date = analyze_statement(
        ticker, name, safe_df(ticker_obj.balance_sheet), BALANCE_KEYS, "balance"
    )
    docs.append(FinancialDoc(
        source      = "yfinance",
        entity      = ticker,
        entity_type = "equity_balance",
        date        = date,
        title       = f"{name} — Balance Sheet {date}",
        body        = body,
        tags        = ["equity", "balance_sheet", "debt", "assets", "solvency"],
        regime      = classify_equity_regime("balance", meta, info),
        meta        = meta,
    ))

    # Cash flow
    body, meta, date = analyze_statement(
        ticker, name, safe_df(ticker_obj.cashflow), CASHFLOW_KEYS, "cashflow"
    )
    docs.append(FinancialDoc(
        source      = "yfinance",
        entity      = ticker,
        entity_type = "equity_cashflow",
        date        = date,
        title       = f"{name} — Cash Flow {date}",
        body        = body,
        tags        = ["equity", "cash_flow", "fcf", "capex", "buybacks"],
        regime      = classify_equity_regime("cashflow", meta, info),
        meta        = meta,
    ))

    # Price summary
    body, meta, date = analyze_price(ticker, name, info)
    docs.append(FinancialDoc(
        source      = "yfinance",
        entity      = ticker,
        entity_type = "equity_price",
        date        = date,
        title       = f"{name} — Price Summary {date}",
        body        = body,
        tags        = ["equity", "price", "technicals", "momentum", "beta"],
        regime      = classify_equity_regime("price", meta, info),
        meta        = meta,
    ))

    return docs



def load_all_yfinance(tickers: list[str] = None) -> list[FinancialDoc]:
    if tickers is None:
        tickers = [t for t, cfg in TICKER_REGISTRY.items() if cfg.tier == 1]

    all_docs = []
    for ticker in tickers:
        try:
            obj  = fetch_yfinance(ticker)
            docs = normalize_yfinance(ticker, obj)
            all_docs.extend(docs)
            logger.info("[yfinance] %s → %d docs", ticker, len(docs))
        except Exception as e:
            logger.error("[yfinance] %s failed: %s", ticker, e)
        time.sleep(1)   # Yahoo rate limit guard
    return all_docs