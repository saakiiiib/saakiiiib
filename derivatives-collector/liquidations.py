"""Live liquidation streams.

    python3 liquidations.py

These are REAL liquidations reported by the venues as they happen — not a
modelled "heatmap". Public websocket feeds, no key, no account. Each venue
runs in its own task and reconnects on its own, so one dropping out doesn't
stop the others.
"""
import asyncio
import json
import logging
import time

import websockets

import config
import storage

log = logging.getLogger("liquidations")

BYBIT_WS = "wss://stream.bybit.com/v5/public/linear"
BINANCE_WS = "wss://fstream.binance.com/stream"
HL_WS = "wss://api.hyperliquid.xyz/ws"


async def _run_forever(name, coro_factory):
    """Reconnect loop with backoff, so a dropped socket is not a dead feed."""
    delay = 1
    while True:
        try:
            await coro_factory()
            delay = 1
        except Exception as e:
            log.warning("%s stream error: %s (reconnecting in %ss)", name, e, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)


async def bybit_stream(conn):
    symbols = config.SYMBOLS["bybit"]
    async def run():
        async with websockets.connect(BYBIT_WS, ping_interval=20) as ws:
            await ws.send(json.dumps({
                "op": "subscribe",
                "args": [f"allLiquidation.{s}" for s in symbols],
            }))
            log.info("bybit liquidation stream live: %s", ", ".join(symbols))
            async for raw in ws:
                msg = json.loads(raw)
                for item in msg.get("data", []) or []:
                    price, qty = float(item["p"]), float(item["v"])
                    # Bybit reports the side of the order that FILLED the
                    # liquidation, so it is the opposite of the position closed.
                    side = "short" if item["S"] == "Buy" else "long"
                    storage.insert_liquidations(conn, [{
                        "venue": "bybit", "symbol": item["s"], "ts": int(item["T"]),
                        "side": side, "price": price, "qty": qty, "usd": price * qty,
                    }])
                    log.info("bybit %s %s liq %.4f @ %.2f ($%.0f)",
                             item["s"], side, qty, price, price * qty)
    await _run_forever("bybit", run)


async def binance_stream(conn):
    symbols = [s.lower() for s in config.SYMBOLS["binance"]]
    url = f"{BINANCE_WS}?streams={'/'.join(f'{s}@forceOrder' for s in symbols)}"
    async def run():
        async with websockets.connect(url, ping_interval=20) as ws:
            log.info("binance liquidation stream live: %s", ", ".join(symbols))
            async for raw in ws:
                o = json.loads(raw).get("data", {}).get("o")
                if not o:
                    continue
                price, qty = float(o["ap"] or o["p"]), float(o["q"])
                side = "long" if o["S"] == "SELL" else "short"
                storage.insert_liquidations(conn, [{
                    "venue": "binance", "symbol": o["s"], "ts": int(o["T"]),
                    "side": side, "price": price, "qty": qty, "usd": price * qty,
                }])
                log.info("binance %s %s liq %.4f @ %.2f ($%.0f)",
                         o["s"], side, qty, price, price * qty)
    await _run_forever("binance", run)


async def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    conn = storage.connect()

    tasks = []
    if config.VENUES.get("bybit"):
        tasks.append(bybit_stream(conn))
    if config.VENUES.get("binance"):
        tasks.append(binance_stream(conn))

    if not tasks:
        log.error("no liquidation-capable venue enabled in config.py")
        return
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
