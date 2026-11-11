"""Normalise Snowflake and Databricks billing exports into one cost record shape.

Expected inputs (column names are matched case-insensitively):

  Snowflake  SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
             START_TIME, WAREHOUSE_NAME, CREDITS_USED
  Databricks system.billing.usage
             usage_date, sku_name, usage_quantity, usage_unit  (only DBU rows are costed)

See cloud/*/ for the export queries.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path


class BillingError(ValueError):
    """A billing row could not be interpreted."""


@dataclass(frozen=True)
class UsageRecord:
    day: date
    engine: str
    resource: str      # warehouse name or SKU
    units: float       # credits or DBUs
    usd: float


def _lower_keys(row: dict) -> dict:
    return {str(k).strip().lower(): v for k, v in row.items()}


def _need(row: dict, key: str, line: int):
    if key not in row or row[key] in (None, ""):
        raise BillingError(f"row {line}: missing column {key!r}")
    return row[key]


def _day(text: str, line: int) -> date:
    try:
        return date.fromisoformat(str(text).strip()[:10])
    except ValueError as exc:
        raise BillingError(f"row {line}: unreadable date {text!r}") from exc


def _num(text, line: int, name: str) -> float:
    try:
        v = float(text)
    except (TypeError, ValueError) as exc:
        raise BillingError(f"row {line}: {name} is not a number: {text!r}") from exc
    if v != v or v in (float("inf"), float("-inf")):
        raise BillingError(f"row {line}: {name} is not finite")
    return v


def parse_snowflake(rows, usd_per_credit: float) -> list[UsageRecord]:
    if usd_per_credit <= 0:
        raise BillingError("usd_per_credit must be > 0")
    out = []
    for i, raw in enumerate(rows, start=1):
        r = _lower_keys(raw)
        credits = _num(_need(r, "credits_used", i), i, "credits_used")
        if credits < 0:
            raise BillingError(f"row {i}: negative credits")
        out.append(UsageRecord(_day(_need(r, "start_time", i), i), "snowflake",
                               str(_need(r, "warehouse_name", i)), credits,
                               credits * usd_per_credit))
    return out


def parse_databricks(rows, usd_per_dbu: float, sku_prices: dict | None = None
                     ) -> tuple[list[UsageRecord], int]:
    """Returns (records, skipped_non_dbu_rows). SKU-specific prices override the default."""
    if usd_per_dbu <= 0:
        raise BillingError("usd_per_dbu must be > 0")
    sku_prices = sku_prices or {}
    out, skipped = [], 0
    for i, raw in enumerate(rows, start=1):
        r = _lower_keys(raw)
        if str(_need(r, "usage_unit", i)).strip().upper() != "DBU":
            skipped += 1
            continue
        qty = _num(_need(r, "usage_quantity", i), i, "usage_quantity")
        sku = str(_need(r, "sku_name", i))
        out.append(UsageRecord(_day(_need(r, "usage_date", i), i), "databricks", sku, qty,
                               qty * float(sku_prices.get(sku, usd_per_dbu))))
    return out, skipped


def read_csv(path) -> list[dict]:
    with Path(path).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def daily_series(records: list[UsageRecord]) -> dict:
    """{(engine, resource): (days, usd_per_day)} on a gap-free calendar (missing days = 0)."""
    if not records:
        return {}
    first = min(r.day for r in records)
    last = max(r.day for r in records)
    n = (last - first).days + 1
    days = [date.fromordinal(first.toordinal() + k) for k in range(n)]
    acc: dict = {}
    for r in records:
        acc.setdefault((r.engine, r.resource), [0.0] * n)[(r.day - first).days] += r.usd
    return {k: (days, v) for k, v in sorted(acc.items())}
