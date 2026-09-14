"""Price alerts on the levels you actually care about.

    python3 alerts.py --list      # show configured alerts and their state
    python3 alerts.py --test      # send a test notification, then exit
    python3 alerts.py             # watch continuously

Edit ALERTS below. Each one fires ONCE, then stays quiet — the fire is recorded
in the database, so restarting the script will not spam you. Use --reset to arm
them again.

Notifications go to the terminal always, plus any channel you configure in
NOTIFY (Telegram reaches your phone and is free).
"""
import argparse
import logging
import os
import sys
import time

import requests

import storage
import venues

log = logging.getLogger("alerts")

# ---------------------------------------------------------------- alerts ----
# direction: "below" fires when price <= level, "above" fires when price >= level.
ALERTS = [
    {"id": "btc-entry",     "venue": "bybit", "symbol": "BTCUSDT",
     "direction": "below", "level": 76640,
     "note": "Limit-buy zone — just above the 09-13 flush low (76,624)."},

    {"id": "btc-entry-deep", "venue": "bybit", "symbol": "BTCUSDT",
     "direction": "below", "level": 76380,
     "note": "Patient entry — just above the 24h low (76,347)."},

    {"id": "btc-stop",      "venue": "bybit", "symbol": "BTCUSDT",
     "direction": "below", "level": 76200,
     "note": "STOP LEVEL — thesis is dead below here."},

    {"id": "btc-breakout",  "venue": "bybit", "symbol": "BTCUSDT",
     "direction": "above", "level": 76853,
     "note": "Cleared the ask wall — setup invalidated to the upside."},
]

POLL_SECONDS = 60

# ---------------------------------------------------------- notifications ----
# Secrets come from the environment, never from this file. Nothing here is sent
# anywhere except the channel you configure yourself.
NOTIFY = {
    "terminal": True,
    "desktop": True,                                   # needs notify-send / osascript
    "telegram": bool(os.environ.get("TELEGRAM_BOT_TOKEN")),
    "webhook": bool(os.environ.get("ALERT_WEBHOOK_URL")),  # Discord / Slack / your own
}


def notify(title, body):
    if NOTIFY.get("terminal"):
        print(f"\a\n{'=' * 60}\n  {title}\n  {body}\n{'=' * 60}\n", flush=True)

    if NOTIFY.get("desktop"):
        try:
            if sys.platform == "darwin":
                os.system(f'osascript -e \'display notification "{body}" '
                          f'with title "{title}"\' >/dev/null 2>&1')
            elif sys.platform.startswith("linux"):
                os.system(f'notify-send "{title}" "{body}" >/dev/null 2>&1')
        except Exception as e:
            log.debug("desktop notify failed: %s", e)

    if NOTIFY.get("telegram"):
        try:
            requests.post(
                f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage",
                json={"chat_id": os.environ["TELEGRAM_CHAT_ID"],
                      "text": f"*{title}*\n{body}", "parse_mode": "Markdown"},
                timeout=10).raise_for_status()
        except Exception as e:
            log.warning("telegram notify failed: %s", e)

    if NOTIFY.get("webhook"):
        try:
            requests.post(os.environ["ALERT_WEBHOOK_URL"],
                          json={"content": f"**{title}**\n{body}"}, timeout=10)
        except Exception as e:
            log.warning("webhook notify failed: %s", e)


# ----------------------------------------------------------------- engine ----
def current_price(alert):
    """Fetch the live price for one alert's market."""
    venue, symbol = alert["venue"], alert["symbol"]
    if venue == "bybit":
        return venues.bybit_snapshot(symbol)["prices"][0]["last"]
    if venue == "okx":
        return venues.okx_snapshot(symbol)["prices"][0]["last"]
    if venue == "binance":
        return venues.binance_snapshot(symbol)["prices"][0]["last"]
    if venue == "hyperliquid":
        rows = venues.hyperliquid_snapshot((symbol,))["prices"]
        if not rows:
            raise ValueError(f"hyperliquid has no market {symbol}")
        return rows[0]["last"]
    raise ValueError(f"unknown venue {venue}")


def triggered(alert, price):
    return (price <= alert["level"] if alert["direction"] == "below"
            else price >= alert["level"])


def already_fired(conn, alert_id):
    return conn.execute("SELECT 1 FROM alert_fires WHERE alert_id=?",
                        (alert_id,)).fetchone() is not None


def record_fire(conn, alert_id, price):
    conn.execute("INSERT OR REPLACE INTO alert_fires VALUES (?,?,?)",
                 (alert_id, int(time.time() * 1000), price))
    conn.commit()


def check_all(conn):
    """One pass over every armed alert. Returns how many fired."""
    fired = 0
    # Fetch each market once even if several alerts share it.
    prices, markets = {}, {(a["venue"], a["symbol"]) for a in ALERTS
                           if not already_fired(conn, a["id"])}
    for venue, symbol in markets:
        try:
            prices[(venue, symbol)] = current_price({"venue": venue, "symbol": symbol})
        except Exception as e:
            log.warning("%s %s price unavailable: %s", venue, symbol,
                        venues.brief_error(e))

    for a in ALERTS:
        if already_fired(conn, a["id"]):
            continue
        price = prices.get((a["venue"], a["symbol"]))
        if price is None:
            continue
        arrow = "↓" if a["direction"] == "below" else "↑"
        log.info("%-16s %s %-10s now %,.1f  (target %,.1f)".replace(",", ""),
                 a["id"], arrow, a["symbol"], price, a["level"])
        if triggered(a, price):
            notify(f"{a['symbol']} {arrow} {a['level']:,.0f}",
                   f"{a['note']}\nPrice now: {price:,.1f}  ({a['venue']})")
            record_fire(conn, a["id"], price)
            fired += 1
    return fired


def show(conn):
    print(f"{'ID':<18}{'MARKET':<12}{'DIR':<7}{'LEVEL':>12}{'STATE':>18}")
    print("-" * 67)
    for a in ALERTS:
        row = conn.execute("SELECT price, fired_ts FROM alert_fires WHERE alert_id=?",
                           (a["id"],)).fetchone()
        state = f"fired @ {row[0]:,.0f}" if row else "armed"
        print(f"{a['id']:<18}{a['symbol']:<12}{a['direction']:<7}"
              f"{a['level']:>12,.0f}{state:>18}")
    print("\nEach alert fires once. Re-arm them all with: python3 alerts.py --reset")


def main():
    ap = argparse.ArgumentParser(description="Price alerts on your levels")
    ap.add_argument("--list", action="store_true", help="show alerts and exit")
    ap.add_argument("--test", action="store_true", help="send a test notification")
    ap.add_argument("--reset", action="store_true", help="re-arm every alert")
    ap.add_argument("--once", action="store_true", help="check once, then exit")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        datefmt="%H:%M:%S")
    conn = storage.connect()

    if args.test:
        notify("Test alert", "If you can see this, notifications work.")
        active = [k for k, v in NOTIFY.items() if v]
        print(f"Channels active: {', '.join(active)}")
        return
    if args.reset:
        conn.execute("DELETE FROM alert_fires")
        conn.commit()
        print("All alerts re-armed.")
        return
    if args.list:
        return show(conn)

    armed = sum(1 for a in ALERTS if not already_fired(conn, a["id"]))
    log.info("watching %d armed alert(s), checking every %ds", armed, POLL_SECONDS)
    if not armed:
        log.info("nothing armed — run with --reset to re-arm")
        return

    while True:
        check_all(conn)
        remaining = sum(1 for a in ALERTS if not already_fired(conn, a["id"]))
        if not remaining:
            log.info("every alert has fired — exiting")
            return
        if args.once:
            log.info("%d alert(s) still armed", remaining)
            return
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
