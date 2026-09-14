"""Which venues and symbols to collect.

Flip any venue to False to drop it entirely — the collector just skips it.
No venue here needs a key, an account, or a login.
"""

VENUES = {
    "bybit": True,
    "okx": True,
    "hyperliquid": True,
    "binance": True,      # public market data only; set False to exclude
}

# Per-venue symbol naming differs, so each keeps its own list.
SYMBOLS = {
    "bybit":       ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
    "okx":         ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"],
    "hyperliquid": ["BTC", "ETH", "SOL"],
    "binance":     ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
}

POLL_SECONDS = 300          # 5 min; well inside every venue's public rate limit
BACKFILL_ON_START = True    # pull real OI/funding history the first time through
