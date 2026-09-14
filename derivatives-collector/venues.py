"""Public market-data fetchers.

Every endpoint here is PUBLIC: no API key, no account, no login, no signup.
These are the same numbers shown on each exchange's public charts. Nothing in
this file can read a balance, a position, or an order — there is no auth path.

Each fetcher returns plain dicts ready for storage.py, and raises on failure so
the caller can log the venue and carry on with the others.
"""
import time
import requests

TIMEOUT = 15
UA = {"User-Agent": "derivatives-collector/1.0"}


def _get(url, params=None):
    r = requests.get(url, params=params, timeout=TIMEOUT, headers=UA)
    r.raise_for_status()
    return r.json()


def _post(url, payload):
    r = requests.post(url, json=payload, timeout=TIMEOUT, headers=UA)
    r.raise_for_status()
    return r.json()


def _now_ms():
    return int(time.time() * 1000)


def _funding_bucket(ts_ms, interval_hours):
    """Snap a timestamp down to its funding period.

    Snapshots are polled far more often than funding actually settles, so
    without this every poll would store another row for the same period.
    """
    step = int(interval_hours * 3600 * 1000)
    return (ts_ms // step) * step


# ---------------------------------------------------------------- Bybit ----
BYBIT = "https://api.bybit.com"


def bybit_snapshot(symbol="BTCUSDT"):
    """Ticker gives OI, funding and all three prices in one call."""
    d = _get(f"{BYBIT}/v5/market/tickers",
             {"category": "linear", "symbol": symbol})["result"]["list"][0]
    ts = _now_ms()
    last = float(d["lastPrice"])
    oi_base = float(d["openInterest"])
    return {
        "open_interest": [{"venue": "bybit", "symbol": symbol, "ts": ts,
                           "oi_base": oi_base, "oi_usd": oi_base * last}],
        "funding": [{"venue": "bybit", "symbol": symbol,
                     "ts": _funding_bucket(ts, 8),
                     "rate": float(d["fundingRate"])}],
        "prices": [{"venue": "bybit", "symbol": symbol, "ts": ts, "last": last,
                    "mark": float(d["markPrice"]), "index_px": float(d["indexPrice"])}],
    }


def bybit_oi_history(symbol="BTCUSDT", interval="5min", limit=200):
    """Backfill real OI history — this is what a single snapshot can't give you."""
    d = _get(f"{BYBIT}/v5/market/open-interest",
             {"category": "linear", "symbol": symbol,
              "intervalTime": interval, "limit": limit})["result"]["list"]
    return [{"venue": "bybit", "symbol": symbol, "ts": int(x["timestamp"]),
             "oi_base": float(x["openInterest"]), "oi_usd": None} for x in d]


def bybit_funding_history(symbol="BTCUSDT", limit=200):
    d = _get(f"{BYBIT}/v5/market/funding/history",
             {"category": "linear", "symbol": symbol, "limit": limit})["result"]["list"]
    return [{"venue": "bybit", "symbol": symbol,
             "ts": int(x["fundingRateTimestamp"]), "rate": float(x["fundingRate"])}
            for x in d]


def bybit_long_short(symbol="BTCUSDT", period="5min", limit=50):
    d = _get(f"{BYBIT}/v5/market/account-ratio",
             {"category": "linear", "symbol": symbol,
              "period": period, "limit": limit})["result"]["list"]
    return [{"venue": "bybit", "symbol": symbol, "ts": int(x["timestamp"]),
             "long_ratio": float(x["buyRatio"]), "short_ratio": float(x["sellRatio"])}
            for x in d]


# ------------------------------------------------------------------ OKX ----
OKX = "https://www.okx.com"


def okx_snapshot(inst_id="BTC-USDT-SWAP"):
    oi = _get(f"{OKX}/api/v5/public/open-interest",
              {"instType": "SWAP", "instId": inst_id})["data"][0]
    fr = _get(f"{OKX}/api/v5/public/funding-rate", {"instId": inst_id})["data"][0]
    tk = _get(f"{OKX}/api/v5/market/ticker", {"instId": inst_id})["data"][0]
    ts = int(oi["ts"])
    return {
        "open_interest": [{"venue": "okx", "symbol": inst_id, "ts": ts,
                           "oi_base": float(oi["oiCcy"]), "oi_usd": float(oi.get("oiUsd") or 0) or None}],
        "funding": [{"venue": "okx", "symbol": inst_id, "ts": int(fr["fundingTime"]),
                     "rate": float(fr["fundingRate"])}],
        "prices": [{"venue": "okx", "symbol": inst_id, "ts": ts,
                    "last": float(tk["last"]), "mark": None, "index_px": None}],
    }


def okx_funding_history(inst_id="BTC-USDT-SWAP", limit=100):
    d = _get(f"{OKX}/api/v5/public/funding-rate-history",
             {"instId": inst_id, "limit": limit})["data"]
    return [{"venue": "okx", "symbol": inst_id, "ts": int(x["fundingTime"]),
             "rate": float(x["realizedRate"])} for x in d]


def okx_long_short(ccy="BTC", period="5m"):
    d = _get(f"{OKX}/api/v5/rubik/stat/contracts/long-short-account-ratio",
             {"ccy": ccy, "period": period})["data"]
    out = []
    for ts, ratio in d:
        r = float(ratio)                      # OKX reports long/short as a single ratio
        longs = r / (1 + r)
        out.append({"venue": "okx", "symbol": ccy, "ts": int(ts),
                    "long_ratio": longs, "short_ratio": 1 - longs})
    return out


# ---------------------------------------------------------- Hyperliquid ----
HL = "https://api.hyperliquid.xyz/info"


def hyperliquid_snapshot(coins=("BTC", "ETH", "SOL")):
    """Fully on-chain venue: the numbers are verifiable, not self-reported."""
    meta, ctxs = _post(HL, {"type": "metaAndAssetCtxs"})
    ts = _now_ms()
    wanted = set(coins)
    oi_rows, fr_rows, px_rows = [], [], []
    for asset, ctx in zip(meta["universe"], ctxs):
        name = asset["name"]
        if name not in wanted:
            continue
        mark = float(ctx["markPx"])
        oi_base = float(ctx["openInterest"])
        oi_rows.append({"venue": "hyperliquid", "symbol": name, "ts": ts,
                        "oi_base": oi_base, "oi_usd": oi_base * mark})
        fr_rows.append({"venue": "hyperliquid", "symbol": name,
                        "ts": _funding_bucket(ts, 1),
                        "rate": float(ctx["funding"])})
        px_rows.append({"venue": "hyperliquid", "symbol": name, "ts": ts,
                        "last": mark, "mark": mark,
                        "index_px": float(ctx.get("oraclePx") or mark)})
    return {"open_interest": oi_rows, "funding": fr_rows, "prices": px_rows}


# -------------------------------------------------------------- Binance ----
# Public market data only. No key, no account — same as every venue above.
BINANCE = "https://fapi.binance.com"


def binance_snapshot(symbol="BTCUSDT"):
    oi = _get(f"{BINANCE}/fapi/v1/openInterest", {"symbol": symbol})
    pi = _get(f"{BINANCE}/fapi/v1/premiumIndex", {"symbol": symbol})
    ts = int(oi["time"])
    mark = float(pi["markPrice"])
    oi_base = float(oi["openInterest"])
    return {
        "open_interest": [{"venue": "binance", "symbol": symbol, "ts": ts,
                           "oi_base": oi_base, "oi_usd": oi_base * mark}],
        "funding": [{"venue": "binance", "symbol": symbol,
                     "ts": _funding_bucket(ts, 8),
                     "rate": float(pi["lastFundingRate"])}],
        "prices": [{"venue": "binance", "symbol": symbol, "ts": ts, "last": mark,
                    "mark": mark, "index_px": float(pi["indexPrice"])}],
    }


def binance_oi_history(symbol="BTCUSDT", period="5m", limit=500):
    d = _get(f"{BINANCE}/futures/data/openInterestHist",
             {"symbol": symbol, "period": period, "limit": limit})
    return [{"venue": "binance", "symbol": symbol, "ts": int(x["timestamp"]),
             "oi_base": float(x["sumOpenInterest"]),
             "oi_usd": float(x["sumOpenInterestValue"])} for x in d]


def binance_funding_history(symbol="BTCUSDT", limit=100):
    d = _get(f"{BINANCE}/fapi/v1/fundingRate", {"symbol": symbol, "limit": limit})
    return [{"venue": "binance", "symbol": symbol, "ts": int(x["fundingTime"]),
             "rate": float(x["fundingRate"])} for x in d]


def binance_long_short(symbol="BTCUSDT", period="5m", limit=100):
    d = _get(f"{BINANCE}/futures/data/globalLongShortAccountRatio",
             {"symbol": symbol, "period": period, "limit": limit})
    return [{"venue": "binance", "symbol": symbol, "ts": int(x["timestamp"]),
             "long_ratio": float(x["longAccount"]),
             "short_ratio": float(x["shortAccount"])} for x in d]
