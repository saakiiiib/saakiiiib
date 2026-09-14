"""Read back what the collector stored.

    python3 report.py             # current snapshot across venues
    python3 report.py --oi BTC    # how open interest moved
    python3 report.py --liqs 24   # liquidations over the last N hours
"""
import argparse
import time

import storage


def _fmt_usd(v):
    if v is None:
        return "n/a"
    for unit, size in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(v) >= size:
            return f"${v / size:.2f}{unit}"
    return f"${v:.0f}"


def snapshot(conn):
    """Latest stored row per venue/symbol — OI, funding and price side by side."""
    rows = conn.execute("""
        SELECT o.venue, o.symbol, o.oi_base, o.oi_usd, o.ts,
               (SELECT rate FROM funding f WHERE f.venue=o.venue AND f.symbol=o.symbol
                 ORDER BY f.ts DESC LIMIT 1),
               (SELECT last FROM prices p WHERE p.venue=o.venue AND p.symbol=o.symbol
                 ORDER BY p.ts DESC LIMIT 1)
        FROM open_interest o
        JOIN (SELECT venue, symbol, MAX(ts) AS mts FROM open_interest
              GROUP BY venue, symbol) m
          ON o.venue=m.venue AND o.symbol=m.symbol AND o.ts=m.mts
        ORDER BY o.symbol, o.venue
    """).fetchall()

    if not rows:
        print("No data yet — run: python3 collector.py --once")
        return

    print(f"{'VENUE':<13}{'SYMBOL':<16}{'PRICE':>12}{'OPEN INTEREST':>16}{'FUNDING':>11}")
    print("-" * 68)
    for venue, symbol, oi_base, oi_usd, _ts, rate, last in rows:
        usd = oi_usd if oi_usd else (oi_base * last if oi_base and last else None)
        funding = f"{rate * 100:+.4f}%" if rate is not None else "n/a"
        price = f"{last:,.2f}" if last else "n/a"
        print(f"{venue:<13}{symbol:<16}{price:>12}{_fmt_usd(usd):>16}{funding:>11}")

    print("\nFunding positive = longs pay shorts (crowd is long).")
    print("Funding negative = shorts pay longs (crowd is short).")


def oi_change(conn, coin, hours=24):
    """OI now vs N hours ago. Rising OI + rising price = new money, not a squeeze."""
    cutoff = int((time.time() - hours * 3600) * 1000)
    rows = conn.execute("""
        SELECT venue, symbol,
               (SELECT oi_base FROM open_interest a
                 WHERE a.venue=o.venue AND a.symbol=o.symbol
                 ORDER BY a.ts DESC LIMIT 1),
               (SELECT oi_base FROM open_interest b
                 WHERE b.venue=o.venue AND b.symbol=o.symbol AND b.ts>=?
                 ORDER BY b.ts ASC LIMIT 1),
               (SELECT MAX(ts) - MIN(ts) FROM open_interest c
                 WHERE c.venue=o.venue AND c.symbol=o.symbol AND c.ts>=?)
        FROM open_interest o
        WHERE o.symbol LIKE ?
        GROUP BY o.venue, o.symbol
    """, (cutoff, cutoff, f"%{coin.upper()}%")).fetchall()

    if not rows:
        print(f"No stored history for {coin}. Let the collector run a while.")
        return

    print(f"Open interest change over ~{hours}h\n")
    print(f"{'VENUE':<13}{'SYMBOL':<16}{'THEN':>14}{'NOW':>14}{'CHANGE':>12}")
    print("-" * 69)

    thin = False
    for venue, symbol, now, then, span_ms in rows:
        if not now or not then:
            continue
        # A venue with one snapshot would otherwise report a confident 0.00%.
        # Only claim a change once the samples actually span some time.
        if not span_ms or span_ms < 600_000:
            change, thin = "no history", True
        else:
            change = f"{(now - then) / then * 100:.2f}%" if then else "n/a"
        print(f"{venue:<13}{symbol:<16}{then:>14,.1f}{now:>14,.1f}{change:>12}")

    if thin:
        print("\n'no history' = only one sample so far; keep collector.py running.")


def liquidations(conn, hours=24):
    cutoff = int((time.time() - hours * 3600) * 1000)
    rows = conn.execute("""
        SELECT symbol, side, COUNT(*), SUM(usd)
        FROM liquidations WHERE ts >= ?
        GROUP BY symbol, side ORDER BY SUM(usd) DESC
    """, (cutoff,)).fetchall()

    if not rows:
        print("No liquidations recorded — is liquidations.py running?")
        return

    print(f"Liquidations, last {hours}h\n")
    print(f"{'SYMBOL':<14}{'SIDE':<8}{'COUNT':>8}{'TOTAL':>14}")
    print("-" * 44)
    for symbol, side, count, usd in rows:
        print(f"{symbol:<14}{side:<8}{count:>8}{_fmt_usd(usd):>14}")

    longs = sum(u or 0 for s, sd, c, u in rows if sd == "long")
    shorts = sum(u or 0 for s, sd, c, u in rows if sd == "short")
    print(f"\nLongs liquidated:  {_fmt_usd(longs)}")
    print(f"Shorts liquidated: {_fmt_usd(shorts)}")


def main():
    ap = argparse.ArgumentParser(description="Report on collected derivatives data")
    ap.add_argument("--oi", metavar="COIN", help="open interest change for a coin")
    ap.add_argument("--liqs", nargs="?", type=int, const=24, metavar="HOURS",
                    help="liquidation totals over the last N hours")
    ap.add_argument("--hours", type=int, default=24, help="lookback for --oi")
    args = ap.parse_args()

    conn = storage.connect()
    if args.oi:
        oi_change(conn, args.oi, args.hours)
    elif args.liqs is not None:
        liquidations(conn, args.liqs)
    else:
        snapshot(conn)


if __name__ == "__main__":
    main()
