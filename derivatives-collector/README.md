# Derivatives Collector

Collects public crypto derivatives data — open interest, funding rates,
long/short ratios and **real liquidations** — into a local SQLite file, so you
build your own history instead of paying for someone else's.

## What it costs

Nothing. Every endpoint used here is public: **no API key, no account, no
login, no signup.** These are the same numbers on each exchange's public
charts. There is no authentication path in this code, so it cannot read a
balance, a position, or an order — on any venue.

## Venues

| Venue | Open interest | Funding | Long/short | Liquidations |
|---|---|---|---|---|
| Bybit | ✅ + history | ✅ + history | ✅ | ✅ live stream |
| OKX | ✅ | ✅ + history | ✅ | — |
| Hyperliquid | ✅ | ✅ | — | — |
| Binance | ✅ + history | ✅ + history | ✅ | ✅ live stream |

Hyperliquid is fully on-chain, so its numbers are independently verifiable
rather than self-reported.

## Setup

```bash
pip install -r requirements.txt
```

Python 3.9+. Two dependencies, both well-known.

## Use

```bash
python3 collector.py --once     # one pass (also backfills real OI/funding history)
python3 collector.py            # keep running, polls every 5 minutes
python3 liquidations.py         # live liquidation feed (separate terminal)

python3 alerts.py --test        # check notifications work
python3 alerts.py --list        # show your alert levels
python3 alerts.py               # watch levels, notify when hit

python3 report.py               # current snapshot across all venues
python3 report.py --oi BTC      # how open interest moved
python3 report.py --liqs 24     # liquidation totals, last 24h
```

Run `collector.py` and `liquidations.py` together in two terminals and leave
them going — that's how the history builds up.

## Alerts

`alerts.py` watches price levels and notifies you when one is hit — the job
people normally use TradingView alerts for, except free and running on your
own machine.

Edit the `ALERTS` list in `alerts.py`:

```python
{"id": "btc-entry", "venue": "bybit", "symbol": "BTCUSDT",
 "direction": "below", "level": 76640,
 "note": "Limit-buy zone."},
```

Each alert fires **once** and is then recorded in the database, so restarting
the script never re-sends it. Re-arm everything with `alerts.py --reset`.

### Getting alerts on your phone

Terminal and desktop notifications work with no setup. For your phone, add
Telegram — free, and about two minutes of work:

1. Message [@BotFather](https://t.me/botfather) on Telegram, send `/newbot`
2. Message your new bot once, then open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` to find your chat id
3. Export both before running:

```bash
export TELEGRAM_BOT_TOKEN="your-token"
export TELEGRAM_CHAT_ID="your-chat-id"
python3 alerts.py --test
```

A Discord or Slack webhook works too — set `ALERT_WEBHOOK_URL`.

**Keep these in your shell or a `.env` file, never in the code**, and never
paste them into a chat — a bot token lets anyone send messages as your bot.

## Choosing venues

Edit `config.py`. Set any venue to `False` to drop it completely:

```python
VENUES = {
    "bybit": True,
    "okx": True,
    "hyperliquid": True,
    "binance": False,     # excluded
}
```

Symbols are per-venue in the same file, since each names its markets
differently.

## Reading the output

- **Funding positive** → longs pay shorts, the crowd is positioned long
- **Funding negative** → shorts pay longs, the crowd is positioned short
- **OI rising + price rising** → new money entering, not just a short squeeze
- **OI falling + price moving fast** → positions being closed or liquidated
- **Longs liquidated ≫ shorts** → a flush downward; the reverse is a squeeze up

## On liquidation heatmaps

This stores liquidations that **actually happened**, as the venues report them.

It deliberately does not draw a "liquidation heatmap". No exchange publishes
where liquidations sit — heatmaps are *models* that infer positions from open
interest and assume common leverage tiers. That is an estimate presented as
data. Real fills plus real order-book depth are more honest inputs.

## Troubleshooting

If every venue fails, the collector says so plainly and exits with code 1:

```
WARNING bybit        BTCUSDT        blocked by a network proxy
ERROR   all 10 venue requests failed — nothing stored
```

Common causes:

- **"cannot reach host"** — you're offline, or a firewall is in the way.
- **"blocked by a network proxy"** — a corporate/VPN proxy is intercepting.
- **"access denied (HTTP 403)"** — that venue blocks your region. Set it to
  `False` in `config.py`; the others keep working.
- **"rate limited (HTTP 429)"** — raise `POLL_SECONDS`.
- **"unexpected response shape"** — that venue changed its API. Only the
  affected venue stops; the rest carry on.

A single venue failing is never fatal — it is logged and skipped.

## Notes

- Polling every 5 minutes sits well inside every venue's public rate limits.
- A venue that errors is logged and skipped; the rest keep running.
- Rows are keyed on (venue, symbol, timestamp), so re-runs backfill without
  creating duplicates.
- `derivs.db` is gitignored — your collected data stays local.
- Funding timestamps are bucketed to the venue's settlement interval, so
  polling every 5 minutes doesn't store hundreds of duplicate funding rows.
- `report.py --oi` prints `no history` rather than a misleading `0.00%` when
  only one sample exists so far.

## Caution

This is a data collection tool, not trading advice and not a trading system.
It places no orders and holds no keys. Crypto derivatives are high risk; open
interest and funding describe positioning, they do not predict price.
