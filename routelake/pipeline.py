"""Medallion pipeline (bronze -> silver -> gold) on SQLite.

SQLite stands in for the warehouse locally so the *logic* is testable offline:
idempotent batches, quarantine with reason codes, first-write-wins dedup,
late-arrival flagging, reconciliation, atomic transactions. The same SQL shapes
port to Delta/Iceberg tables on Databricks or Snowflake.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass

from .contracts import Contract, parse_ts

SCHEMA = """
CREATE TABLE IF NOT EXISTS bronze_events(
    batch_id TEXT NOT NULL, seq INTEGER NOT NULL, payload TEXT NOT NULL,
    processed INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(batch_id, seq));
CREATE TABLE IF NOT EXISTS silver_events(
    event_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, event_type TEXT NOT NULL,
    category TEXT NOT NULL, price REAL NOT NULL, quantity INTEGER NOT NULL,
    event_ts TEXT NOT NULL, event_date TEXT NOT NULL, ingest_ts TEXT NOT NULL,
    is_late INTEGER NOT NULL, batch_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS quarantine_events(
    batch_id TEXT NOT NULL, seq INTEGER NOT NULL, reasons TEXT NOT NULL,
    payload TEXT NOT NULL, PRIMARY KEY(batch_id, seq));
CREATE TABLE IF NOT EXISTS batch_log(
    batch_id TEXT PRIMARY KEY, received INTEGER NOT NULL,
    silver_inserted INTEGER NOT NULL, duplicates INTEGER NOT NULL,
    quarantined INTEGER NOT NULL, late INTEGER NOT NULL);
"""


class BatchConflictError(ValueError):
    """A batch_id was reused with different content."""


def connect(path: str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.isolation_level = None          # we manage transactions explicitly
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection):
    conn.execute("BEGIN")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def init_schema(conn: sqlite3.Connection) -> None:
    with transaction(conn):
        for stmt in filter(None, (s.strip() for s in SCHEMA.split(";"))):
            conn.execute(stmt)


@dataclass(frozen=True)
class BatchResult:
    batch_id: str
    received: int
    silver_inserted: int
    duplicates: int
    quarantined: int
    late: int
    replayed: bool = False


def _dump(record) -> str:
    return json.dumps(record, sort_keys=True, default=repr)


def run_batch(conn: sqlite3.Connection, batch_id: str, records: list,
              contract: Contract, late_after_hours: float = 48.0) -> BatchResult:
    """Ingest one batch atomically. Replaying identical content is a no-op."""
    payloads = [_dump(r) for r in records]
    with transaction(conn):
        logged = conn.execute(
            "SELECT received FROM batch_log WHERE batch_id=?", (batch_id,)).fetchone()
        if logged is not None:
            existing = [p for (p,) in conn.execute(
                "SELECT payload FROM bronze_events WHERE batch_id=? ORDER BY seq",
                (batch_id,))]
            if existing != payloads:
                raise BatchConflictError(
                    f"batch {batch_id!r} already ingested with different content")
            return BatchResult(batch_id, logged[0], 0, 0, 0, 0, replayed=True)

        conn.executemany(
            "INSERT INTO bronze_events(batch_id, seq, payload) VALUES (?,?,?)",
            [(batch_id, i, p) for i, p in enumerate(payloads)])

        inserted = dups = quarantined = late = 0
        pending = conn.execute(
            "SELECT seq, payload FROM bronze_events WHERE batch_id=? AND processed=0 "
            "ORDER BY seq", (batch_id,)).fetchall()
        for seq, payload in pending:
            record = json.loads(payload)
            reasons = contract.validate(record)
            if reasons:
                conn.execute(
                    "INSERT INTO quarantine_events(batch_id, seq, reasons, payload) "
                    "VALUES (?,?,?,?)", (batch_id, seq, ",".join(reasons), payload))
                quarantined += 1
                continue
            event_dt = parse_ts(record["event_ts"])
            ingest_dt = parse_ts(record["ingest_ts"])
            is_late = int((ingest_dt - event_dt).total_seconds() > late_after_hours * 3600)
            cur = conn.execute(
                "INSERT OR IGNORE INTO silver_events(event_id, user_id, event_type, "
                "category, price, quantity, event_ts, event_date, ingest_ts, is_late, "
                "batch_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (record["event_id"], record["user_id"], record["event_type"],
                 record["category"], float(record["price"]), int(record["quantity"]),
                 event_dt.isoformat(), event_dt.date().isoformat(),
                 ingest_dt.isoformat(), is_late, batch_id))
            if cur.rowcount == 1:
                inserted += 1
                late += is_late
            else:
                dups += 1
        conn.execute("UPDATE bronze_events SET processed=1 WHERE batch_id=?", (batch_id,))
        conn.execute(
            "INSERT INTO batch_log VALUES (?,?,?,?,?,?)",
            (batch_id, len(records), inserted, dups, quarantined, late))
    return BatchResult(batch_id, len(records), inserted, dups, quarantined, late)


GOLD_SQL = (
    "DROP TABLE IF EXISTS gold_daily_revenue",
    """CREATE TABLE gold_daily_revenue AS
       SELECT event_date, category,
              SUM(CASE WHEN event_type='purchase' THEN 1 ELSE 0 END) AS purchases,
              SUM(CASE WHEN event_type='purchase' THEN quantity ELSE 0 END) AS units,
              ROUND(SUM(CASE WHEN event_type='purchase' THEN price*quantity ELSE 0 END), 2) AS revenue
       FROM silver_events GROUP BY event_date, category ORDER BY event_date, category""",
    "DROP TABLE IF EXISTS gold_funnel",
    """CREATE TABLE gold_funnel AS
       SELECT category,
              SUM(CASE WHEN event_type='view' THEN 1 ELSE 0 END) AS views,
              SUM(CASE WHEN event_type='add_to_cart' THEN 1 ELSE 0 END) AS carts,
              SUM(CASE WHEN event_type='purchase' THEN 1 ELSE 0 END) AS purchases,
              CASE WHEN SUM(CASE WHEN event_type='view' THEN 1 ELSE 0 END)=0 THEN NULL
                   ELSE ROUND(100.0*SUM(CASE WHEN event_type='add_to_cart' THEN 1 ELSE 0 END)
                        / SUM(CASE WHEN event_type='view' THEN 1 ELSE 0 END), 2) END AS view_to_cart_pct
       FROM silver_events GROUP BY category ORDER BY category""",
)


def build_gold(conn: sqlite3.Connection) -> None:
    """Full-refresh gold tables atomically (idempotent)."""
    with transaction(conn):
        for stmt in GOLD_SQL:
            conn.execute(stmt)


def reconcile(conn: sqlite3.Connection) -> list[str]:
    """Return a list of integrity failures; empty means every control passed."""
    failures: list[str] = []
    q = lambda sql, *a: conn.execute(sql, a).fetchone()[0]  # noqa: E731

    for b, rec, ins, dup, quar in conn.execute(
            "SELECT batch_id, received, silver_inserted, duplicates, quarantined "
            "FROM batch_log").fetchall():
        if rec != ins + dup + quar:
            failures.append(f"{b}: received {rec} != silver {ins} + dup {dup} + quarantine {quar}")
        in_bronze = q("SELECT COUNT(*) FROM bronze_events WHERE batch_id=?", b)
        if in_bronze != rec:
            failures.append(f"{b}: bronze rows {in_bronze} != received {rec}")
        if q("SELECT COUNT(*) FROM bronze_events WHERE batch_id=? AND processed=0", b):
            failures.append(f"{b}: unprocessed bronze rows remain")

    logged_silver = q("SELECT COALESCE(SUM(silver_inserted),0) FROM batch_log")
    if logged_silver != q("SELECT COUNT(*) FROM silver_events"):
        failures.append("silver row count differs from batch_log total")
    logged_quar = q("SELECT COALESCE(SUM(quarantined),0) FROM batch_log")
    if logged_quar != q("SELECT COUNT(*) FROM quarantine_events"):
        failures.append("quarantine row count differs from batch_log total")

    has_gold = q("SELECT COUNT(*) FROM sqlite_master WHERE name='gold_daily_revenue'")
    if has_gold:
        silver_rev = q("SELECT COALESCE(SUM(price*quantity),0) FROM silver_events "
                       "WHERE event_type='purchase'")
        gold_rev = q("SELECT COALESCE(SUM(revenue),0) FROM gold_daily_revenue")
        groups = q("SELECT COUNT(*) FROM gold_daily_revenue")
        if abs(silver_rev - gold_rev) > 0.005 * max(groups, 1) + 1e-6:
            failures.append(f"gold revenue {gold_rev:.2f} != silver revenue {silver_rev:.2f}")
    return failures
