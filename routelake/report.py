"""Run the whole RouteLake demo and render JSON + Markdown reports."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from . import CONFIG_DIR, CONTRACT_DIR
from .anomaly import detect
from .billing import daily_series, parse_databricks, parse_snowflake, read_csv
from .contracts import Contract
from .cost_model import Assumptions, load_workloads
from .events import GenConfig, generate_events, split_batches
from .fixtures import (DATABRICKS_COLUMNS, SNOWFLAKE_COLUMNS, databricks_rows,
                       snowflake_rows, write_csv)
from .pipeline import build_gold, connect, init_schema, reconcile, run_batch
from .router import route_all, summarize

USD_PER_CREDIT = 3.0
USD_PER_DBU = 0.7


def run_pipeline_demo(cfg: GenConfig, n_batches: int = 5, db_path: str = ":memory:") -> dict:
    events, truth = generate_events(cfg)
    contract = Contract.load(CONTRACT_DIR / "events_v1.json")
    conn = connect(db_path)
    init_schema(conn)
    batches = split_batches(events, n_batches)
    results = [run_batch(conn, f"batch-{i + 1:02d}", b, contract) for i, b in enumerate(batches)]
    replay = run_batch(conn, "batch-01", batches[0], contract)      # idempotency proof
    build_gold(conn)
    failures = reconcile(conn)
    q = lambda sql: conn.execute(sql).fetchone()[0]                 # noqa: E731
    reasons: dict = {}
    for (r,) in conn.execute("SELECT reasons FROM quarantine_events"):
        for code in r.split(","):
            reasons[code] = reasons.get(code, 0) + 1
    out = {
        "ground_truth": asdict(truth),
        "batches": [asdict(r) for r in results],
        "replay_was_noop": replay.replayed and replay.silver_inserted == 0,
        "silver_rows": q("SELECT COUNT(*) FROM silver_events"),
        "quarantine_rows": q("SELECT COUNT(*) FROM quarantine_events"),
        "late_rows": q("SELECT COALESCE(SUM(is_late),0) FROM silver_events"),
        "duplicates_dropped": sum(r.duplicates for r in results),
        "quarantine_reasons": dict(sorted(reasons.items())),
        "total_revenue": q("SELECT ROUND(COALESCE(SUM(revenue),0),2) FROM gold_daily_revenue"),
        "funnel": [dict(zip(("category", "views", "carts", "purchases", "view_to_cart_pct"), r))
                   for r in conn.execute("SELECT * FROM gold_funnel")],
        "reconciliation_failures": failures,
        "matches_ground_truth": (
            q("SELECT COUNT(*) FROM silver_events") == truth.valid_unique
            and q("SELECT COUNT(*) FROM quarantine_events") == truth.defects
            and sum(r.duplicates for r in results) == truth.duplicates
            and q("SELECT COALESCE(SUM(is_late),0) FROM silver_events") == truth.late),
    }
    conn.close()
    return out


def run_routing_demo(assumptions_path=None, workloads_path=None) -> dict:
    a = Assumptions.load(assumptions_path or CONFIG_DIR / "assumptions.json")
    ws = load_workloads(workloads_path or CONFIG_DIR / "workloads.json", a)
    decisions = route_all(ws, a)
    return {
        "disclaimer": a.raw.get("disclaimer", ""),
        "decisions": [{
            "workload": d.workload, "kind": d.kind, "engine": d.chosen.engine,
            "size": d.chosen.size, "runtime_s": round(d.chosen.runtime_s, 1),
            "daily_usd": round(d.chosen.daily_usd, 2), "feasible": d.chosen.feasible,
            "reason": d.reason,
            "alternatives": {n: {"size": p.size, "runtime_s": round(p.runtime_s, 1),
                                 "daily_usd": round(p.daily_usd, 2), "feasible": p.feasible}
                             for n, p in d.alternatives.items()},
        } for d in decisions],
        "summary": summarize(decisions, a),
    }


def run_billing_demo(data_dir: Path) -> dict:
    sf_path, db_path = Path(data_dir) / "snowflake_metering.csv", Path(data_dir) / "databricks_usage.csv"
    if not sf_path.exists():
        write_csv(sf_path, SNOWFLAKE_COLUMNS, snowflake_rows())
    if not db_path.exists():
        write_csv(db_path, DATABRICKS_COLUMNS, databricks_rows())
    sf = parse_snowflake(read_csv(sf_path), USD_PER_CREDIT)
    db, skipped = parse_databricks(read_csv(db_path), USD_PER_DBU)
    series = daily_series(sf + db)
    anomalies = detect(series)
    total_by_day: dict = {}
    for _, (days, vals) in series.items():
        for d, v in zip(days, vals):
            total_by_day[d.isoformat()] = total_by_day.get(d.isoformat(), 0.0) + v
    return {
        "records": len(sf) + len(db), "skipped_non_dbu_rows": skipped,
        "total_usd": round(sum(r.usd for r in sf + db), 2),
        "daily_total_usd": {k: round(v, 2) for k, v in sorted(total_by_day.items())},
        "anomalies": [{"day": a.day.isoformat(), "engine": a.engine, "resource": a.resource,
                       "usd": round(a.usd, 2), "baseline_usd": round(a.baseline_usd, 2),
                       "score": round(a.score, 1), "explanation": a.explanation} for a in anomalies],
    }


def build_report(out_dir: Path, data_dir: Path, cfg: GenConfig = GenConfig()) -> dict:
    report = {
        "project": "RouteLake", "author": "Analyst Rushi",
        "pipeline": run_pipeline_demo(cfg),
        "routing": run_routing_demo(),
        "billing": run_billing_demo(data_dir),
    }
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out_dir / "latest.md").write_text(render_markdown(report), encoding="utf-8")
    return report


def render_markdown(r: dict) -> str:
    p, rt, b = r["pipeline"], r["routing"], r["billing"]
    s = rt["summary"]
    lines = [
        "# RouteLake demo report", "", "_By Analyst Rushi. Generated by `python -m routelake demo`._", "",
        "## 1. Pipeline (bronze -> silver -> gold)", "",
        f"- Events received: **{p['ground_truth']['emitted']}** "
        f"({p['ground_truth']['unique_events']} unique + {p['ground_truth']['duplicates']} planted duplicates)",
        f"- Silver rows: **{p['silver_rows']}** | Quarantined: **{p['quarantine_rows']}** | "
        f"Duplicates dropped: **{p['duplicates_dropped']}** | Late-arriving flagged: **{p['late_rows']}**",
        f"- Matches planted ground truth exactly: **{p['matches_ground_truth']}**",
        f"- Replay of batch-01 was a no-op: **{p['replay_was_noop']}**",
        f"- Reconciliation failures: **{len(p['reconciliation_failures'])}**", "",
        "Quarantine reasons: " + ", ".join(f"`{k}` x{v}" for k, v in p["quarantine_reasons"].items()), "",
        "## 2. Workload routing", "", f"> {rt['disclaimer']}", "",
        "| Workload | Engine | Size | Runtime (s) | $/day | SLO |", "|---|---|---|---:|---:|---|",
    ]
    for d in rt["decisions"]:
        lines.append(f"| {d['workload']} | {d['engine']} | {d['size']} | {d['runtime_s']:.0f} | "
                     f"{d['daily_usd']:.2f} | {'met' if d['feasible'] else 'MISSED'} |")
    lines += ["",
              f"Routed: **${s['routed_daily_usd']:.2f}/day** vs all-on-{s['default_engine']}: "
              f"**${s['all_on_engine'][s['default_engine']]['daily_usd']:.2f}/day** "
              f"(**{s['savings_vs_default_pct']:.1f}%** lower, {s['routed_slo_misses']} SLO misses).", "",
              "## 3. Billing anomalies", "",
              f"{b['records']} usage rows analysed, {len(b['anomalies'])} anomalies:", ""]
    lines += [f"- {a['explanation']}" for a in b["anomalies"]] or ["- none"]
    return "\n".join(lines) + "\n"
