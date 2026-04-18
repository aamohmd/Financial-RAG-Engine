from dataclasses import dataclass

@dataclass
class TickerConfig:
    tier: int
    sector: str

TICKER_REGISTRY = {
    "AAPL":  TickerConfig(tier=1, sector="Technology"),
    "MSFT":  TickerConfig(tier=1, sector="Technology"),
    "NVDA":  TickerConfig(tier=1, sector="Semiconductors"),
    "GOOGL": TickerConfig(tier=1, sector="Communication Services"),
    "AMZN":  TickerConfig(tier=1, sector="Consumer Cyclical"),
    "META":  TickerConfig(tier=1, sector="Communication Services"),
    "TSLA":  TickerConfig(tier=1, sector="Consumer Cyclical"),
    "JPM":   TickerConfig(tier=1, sector="Financial Services"),
    "GS":    TickerConfig(tier=1, sector="Financial Services"),
    "SPY":   TickerConfig(tier=1, sector="Index"),
}
