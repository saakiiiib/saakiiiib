"""Poll public derivatives data on a loop and store it locally.

    python3 collector.py            # run forever, polling every 5 minutes
    python3 collector.py --once     # single pass, then exit

A venue that errors is logged and skipped; the others still run. Nothing here
authenticates to anything, so a failure can never affect an account.
"""
import argparse
import logging
import time

import config
import storage
import venues

log = logging.getLogger("collector")


def _store(conn, bundle):
    """Write a {table: rows} bundle and return rows actually added."""
    return sum(storage.upsert(conn, table, rows) for table, rows in bundle.items())


def collect_once(conn, backfill=False):
    written = 0

    for venue, enabled in config.VENUES.items():
        if not enabled:
            continue
        for symbol in config.SYMBOLS.get(venue, []):
            try:
                if venue == "bybit":
                    written += _store(conn, venues.bybit_snapshot(symbol))
                    written += storage.upsert(conn, "long_short",
                                              venues.bybit_long_short(symbol))
                    if backfill:
                        written += storage.upsert(conn, "open_interest",
                                                  venues.bybit_oi_history(symbol))
                        written += storage.upsert(conn, "funding",
                                                  venues.bybit_funding_history(symbol))

                elif venue == "okx":
                    written += _store(conn, venues.okx_snapshot(symbol))
                    if backfill:
                        written += storage.upsert(conn, "funding",
                                                  venues.okx_funding_history(symbol))

                elif venue == "binance":
                    written += _store(conn, venues.binance_snapshot(symbol))
                    written += storage.upsert(conn, "long_short",
                                              venues.binance_long_short(symbol))
                    if backfill:
                        written += storage.upsert(conn, "open_interest",
                                                  venues.binance_oi_history(symbol))
                        written += storage.upsert(conn, "funding",
                                                  venues.binance_funding_history(symbol))

                log.info("%s %s ok", venue, symbol)
            except Exception as e:
                log.warning("%s %s failed: %s", venue, symbol, e)

    # Hyperliquid returns every coin in one call, so it sits outside the symbol loop.
    if config.VENUES.get("hyperliquid"):
        try:
            written += _store(conn, venues.hyperliquid_snapshot(
                tuple(config.SYMBOLS["hyperliquid"])))
            log.info("hyperliquid ok")
        except Exception as e:
            log.warning("hyperliquid failed: %s", e)

    # OKX long/short is per-currency, not per-instrument.
    if config.VENUES.get("okx"):
        for ccy in {s.split("-")[0] for s in config.SYMBOLS["okx"]}:
            try:
                written += storage.upsert(conn, "long_short", venues.okx_long_short(ccy))
            except Exception as e:
                log.warning("okx long/short %s failed: %s", ccy, e)

    return written


def main():
    ap = argparse.ArgumentParser(description="Collect public crypto derivatives data")
    ap.add_argument("--once", action="store_true", help="single pass, then exit")
    ap.add_argument("--no-backfill", action="store_true", help="skip history backfill")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    conn = storage.connect()

    backfill = config.BACKFILL_ON_START and not args.no_backfill
    while True:
        n = collect_once(conn, backfill=backfill)
        log.info("stored %d new rows", n)
        backfill = False          # history only needs pulling once
        if args.once:
            return
        time.sleep(config.POLL_SECONDS)


if __name__ == "__main__":
    main()
