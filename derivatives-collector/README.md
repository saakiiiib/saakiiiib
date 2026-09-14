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

python3 report.py               # current snapshot across all venues
python3 report.py --oi BTC      # how open interest moved
python3 report.py --liqs 24     # liquidation totals, last 24h
```

Run `collector.py` and `liquidations.py` together in two terminals and leave
them going — that's how the history builds up.

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

## Notes

- Polling every 5 minutes sits well inside every venue's public rate limits.
- A venue that errors is logged and skipped; the rest keep running.
- Rows are keyed on (venue, symbol, timestamp), so re-runs backfill without
  creating duplicates.
- `derivs.db` is gitignored — your collected data stays local.

## Caution

This is a data collection tool, not trading advice and not a trading system.
It places no orders and holds no keys. Crypto derivatives are high risk; open
interest and funding describe positioning, they do not predict price.
