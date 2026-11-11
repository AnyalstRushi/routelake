"""Deterministic billing fixtures shaped like the real vendor exports, with a planted spike."""
from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

SNOWFLAKE_COLUMNS = ["START_TIME", "END_TIME", "WAREHOUSE_NAME", "CREDITS_USED_COMPUTE",
                     "CREDITS_USED_CLOUD_SERVICES", "CREDITS_USED"]
DATABRICKS_COLUMNS = ["usage_date", "workspace_id", "sku_name", "usage_unit", "usage_quantity"]

# (warehouse, baseline credits per active hour, active hours)
WAREHOUSES = (("ETL_WH", 3.2, range(1, 5)), ("BI_WH", 1.4, range(8, 19)), ("ADHOC_WH", 0.6, range(9, 18)))
SKUS = (("JOBS_COMPUTE", 410.0), ("SQL_COMPUTE", 190.0), ("ALL_PURPOSE_COMPUTE", 95.0))


def snowflake_rows(seed: int = 7, days: int = 30, start: date = date(2026, 10, 1),
                   spike_day: int = 21, spike_wh: str = "ADHOC_WH", spike_mult: float = 9.0) -> list[dict]:
    rng = random.Random(seed)
    rows = []
    for d in range(days):
        day = start + timedelta(days=d)
        for wh, base, hours in WAREHOUSES:
            for h in hours:
                credits = base * rng.uniform(0.85, 1.15)
                if d == spike_day and wh == spike_wh:
                    credits *= spike_mult
                cloud = credits * 0.02
                rows.append({
                    "START_TIME": f"{day.isoformat()} {h:02d}:00:00.000 +0000",
                    "END_TIME": f"{day.isoformat()} {h + 1:02d}:00:00.000 +0000",
                    "WAREHOUSE_NAME": wh,
                    "CREDITS_USED_COMPUTE": f"{credits:.6f}",
                    "CREDITS_USED_CLOUD_SERVICES": f"{cloud:.6f}",
                    "CREDITS_USED": f"{credits + cloud:.6f}",
                })
    return rows


def databricks_rows(seed: int = 11, days: int = 30, start: date = date(2026, 10, 1),
                    spike_day: int = 14, spike_sku: str = "ALL_PURPOSE_COMPUTE",
                    spike_mult: float = 7.0) -> list[dict]:
    rng = random.Random(seed)
    rows = []
    for d in range(days):
        day = start + timedelta(days=d)
        for sku, base in SKUS:
            qty = base * rng.uniform(0.9, 1.1)
            if d == spike_day and sku == spike_sku:
                qty *= spike_mult
            rows.append({"usage_date": day.isoformat(), "workspace_id": "1234567890123456",
                         "sku_name": sku, "usage_unit": "DBU", "usage_quantity": f"{qty:.4f}"})
    return rows


def write_csv(path, columns: list[str], rows: list[dict]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=columns, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
