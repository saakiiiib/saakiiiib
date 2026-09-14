"""SQLite storage for derivatives market data.

One file, no server, no setup. Every row is (venue, symbol, timestamp)-unique
so re-running the collector backfills without creating duplicates.
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "derivs.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS open_interest (
    venue TEXT NOT NULL,
    symbol TEXT NOT NULL,
    ts INTEGER NOT NULL,           -- unix ms
    oi_base REAL,                  -- open interest in base coin (e.g. BTC)
    oi_usd REAL,                   -- open interest in USD, when the venue gives it
    PRIMARY KEY (venue, symbol, ts)
);

CREATE TABLE IF NOT EXISTS funding (
    venue TEXT NOT NULL,
    symbol TEXT NOT NULL,
    ts INTEGER NOT NULL,
    rate REAL NOT NULL,            -- per-interval rate, e.g. 0.0001 = 0.01%
    PRIMARY KEY (venue, symbol, ts)
);

CREATE TABLE IF NOT EXISTS long_short (
    venue TEXT NOT NULL,
    symbol TEXT NOT NULL,
    ts INTEGER NOT NULL,
    long_ratio REAL,
    short_ratio REAL,
    PRIMARY KEY (venue, symbol, ts)
);

CREATE TABLE IF NOT EXISTS prices (
    venue TEXT NOT NULL,
    symbol TEXT NOT NULL,
    ts INTEGER NOT NULL,
    last REAL,
    mark REAL,
    index_px REAL,
    PRIMARY KEY (venue, symbol, ts)
);

CREATE TABLE IF NOT EXISTS liquidations (
    venue TEXT NOT NULL,
    symbol TEXT NOT NULL,
    ts INTEGER NOT NULL,
    side TEXT NOT NULL,            -- side that got liquidated: 'long' or 'short'
    price REAL NOT NULL,
    qty REAL NOT NULL,
    usd REAL
);

CREATE TABLE IF NOT EXISTS alert_fires (
    alert_id TEXT PRIMARY KEY,     -- stable id, so a restart never re-fires
    fired_ts INTEGER NOT NULL,
    price REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_liq_ts ON liquidations (ts);
CREATE INDEX IF NOT EXISTS idx_liq_sym ON liquidations (symbol, ts);
CREATE INDEX IF NOT EXISTS idx_oi_sym ON open_interest (symbol, ts);
"""


def connect(path=DB_PATH):
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")      # concurrent reader + writer
    conn.executescript(SCHEMA)
    return conn


def upsert(conn, table, rows):
    """Insert rows, silently skipping ones already stored. Returns count written."""
    if not rows:
        return 0
    cols = list(rows[0].keys())
    sql = (
        f"INSERT OR IGNORE INTO {table} ({','.join(cols)}) "
        f"VALUES ({','.join('?' for _ in cols)})"
    )
    cur = conn.executemany(sql, [tuple(r[c] for c in cols) for r in rows])
    conn.commit()
    return cur.rowcount


def insert_liquidations(conn, rows):
    """Liquidations have no natural key, so they append rather than upsert."""
    if not rows:
        return 0
    cur = conn.executemany(
        "INSERT INTO liquidations (venue,symbol,ts,side,price,qty,usd) "
        "VALUES (?,?,?,?,?,?,?)",
        [(r["venue"], r["symbol"], r["ts"], r["side"], r["price"], r["qty"], r.get("usd"))
         for r in rows],
    )
    conn.commit()
    return cur.rowcount
