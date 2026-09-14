"""Poll public derivatives data on a loop and store it locally.

    python3 collector.py            # run forever, polling every 5 minutes
    python3 collector.py --once     # single pass, then exit

A venue that errors is logged and skipped; the others still run. Nothing here
authenticates to anything, so a failure can never affect an account.

Exit codes (so this is safe to put in cron):
    0  at least one venue was collected
    1  every venue failed
"""
import argparse
import logging
import sys
import time

import requests

import config
import storage
import venues

log = logging.getLogger("collector")


def _brief(e):
    """Turn a noisy network traceback into one readable line."""
    if isinstance(e, requests.exceptions.ProxyError):
        return "blocked by a network proxy"
    if isinstance(e, requests.exceptions.ConnectTimeout):
        return "connection timed out"
    if isinstance(e, requests.exceptions.ConnectionError):
        return "cannot reach host (offline, DNS, or firewall)"
    if isinstance(e, requests.exceptions.HTTPError) and e.response is not None:
        code = e.response.status_code
        if code == 429:
            return "rate limited (HTTP 429) — try a longer POLL_SECONDS"
        if code in (403, 451):
            return f"access denied (HTTP {code}) — venue may block your region"
        return f"HTTP {code}"
    if isinstance(e, (KeyError, IndexError, TypeError, ValueError)):
        return f"unexpected response shape ({type(e).__name__}: {e})"
    return f"{type(e).__name__}: {e}"


def _store(conn, bundle):
    """Write a {table: rows} bundle and return rows actually added."""
    return sum(storage.upsert(conn, table, rows) for table, rows in bundle.items())


def collect_once(conn, backfill=False):
    """Returns (rows_written, ok_count, fail_count)."""
    written = ok = failed = 0

    for venue, enabled in config.VENUES.items():
        # Hyperliquid returns every coin in one call, so it is handled below
        # rather than per-symbol. Without this guard the loop would fall
        # through every symbol doing nothing and still log success.
        if not enabled or venue == "hyperliquid":
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
                else:
                    log.warning("%s: no fetcher implemented, skipping", venue)
                    continue

                ok += 1
                log.info("%-12s %-14s ok", venue, symbol)
            except Exception as e:
                failed += 1
                log.warning("%-12s %-14s %s", venue, symbol, _brief(e))

    if config.VENUES.get("hyperliquid"):
        symbols = tuple(config.SYMBOLS.get("hyperliquid", []))
        try:
            written += _store(conn, venues.hyperliquid_snapshot(symbols))
            ok += 1
            log.info("%-12s %-14s ok", "hyperliquid", ",".join(symbols))
        except Exception as e:
            failed += 1
            log.warning("%-12s %-14s %s", "hyperliquid", "", _brief(e))

    # OKX long/short is per-currency, not per-instrument.
    if config.VENUES.get("okx"):
        for ccy in sorted({s.split("-")[0] for s in config.SYMBOLS.get("okx", [])}):
            try:
                written += storage.upsert(conn, "long_short", venues.okx_long_short(ccy))
            except Exception as e:
                log.warning("%-12s %-14s %s", "okx l/s", ccy, _brief(e))

    return written, ok, failed


def main():
    ap = argparse.ArgumentParser(description="Collect public crypto derivatives data")
    ap.add_argument("--once", action="store_true", help="single pass, then exit")
    ap.add_argument("--no-backfill", action="store_true", help="skip history backfill")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    conn = storage.connect()

    if not any(config.VENUES.values()):
        log.error("every venue is disabled in config.py — nothing to collect")
        sys.exit(1)

    backfill = config.BACKFILL_ON_START and not args.no_backfill
    while True:
        written, ok, failed = collect_once(conn, backfill=backfill)

        if ok:
            log.info("stored %d new rows (%d ok, %d failed)", written, ok, failed)
        else:
            log.error("all %d venue requests failed — nothing stored", failed)
            log.error("check your internet connection, or whether your network "
                      "or region blocks these exchanges")
            if args.once:
                sys.exit(1)

        backfill = False          # history only needs pulling once
        if args.once:
            return
        time.sleep(config.POLL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()          # keep Ctrl-C from mangling the shell prompt
