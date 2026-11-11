"""Command line interface: python -m routelake <command>."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from . import CONFIG_DIR, ROOT, SAMPLE_DIR, __version__
from .calibrate import calibrate
from .cost_model import Assumptions, ConfigError, load_workloads
from .events import GenConfig
from .report import build_report, run_routing_demo


def _cmd_demo(args) -> int:
    cfg = GenConfig(seed=args.seed, n_events=args.events)
    r = build_report(Path(args.out), Path(args.data), cfg)
    p, s = r["pipeline"], r["routing"]["summary"]
    print(f"pipeline : silver={p['silver_rows']} quarantine={p['quarantine_rows']} "
          f"dups={p['duplicates_dropped']} late={p['late_rows']} "
          f"ground_truth_match={p['matches_ground_truth']} recon_failures={len(p['reconciliation_failures'])}")
    print(f"routing  : ${s['routed_daily_usd']:.2f}/day vs ${s['all_on_engine'][s['default_engine']]['daily_usd']:.2f}/day "
          f"all-{s['default_engine']} ({s['savings_vs_default_pct']:.1f}% lower), mix={s['engine_mix']}")
    for a in r["billing"]["anomalies"]:
        print(f"anomaly  : {a['explanation']}")
    print(f"reports written to {args.out}/latest.md and latest.json")
    ok = p["matches_ground_truth"] and not p["reconciliation_failures"] and p["replay_was_noop"]
    return 0 if ok else 1


def _cmd_route(args) -> int:
    try:
        out = run_routing_demo(args.assumptions, args.workloads)
    except (ConfigError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(out, indent=2))
    return 0


def _cmd_calibrate(args) -> int:
    try:
        a = Assumptions.load(args.assumptions)
        with open(args.samples, newline="", encoding="utf-8") as fh:
            samples = list(csv.DictReader(fh))
        new, rep = calibrate(a, samples)
        Assumptions.from_dict(new)                      # re-validate before writing
    except (ConfigError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    Path(args.out).write_text(json.dumps(new, indent=2), encoding="utf-8")
    print(json.dumps(rep, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="routelake", description="RouteLake by Analyst Rushi")
    p.add_argument("--version", action="version", version=f"routelake {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo", help="run pipeline + router + billing anomaly demo")
    d.add_argument("--out", default=str(ROOT / "reports"))
    d.add_argument("--data", default=str(SAMPLE_DIR))
    d.add_argument("--seed", type=int, default=42)
    d.add_argument("--events", type=int, default=5000)
    d.set_defaults(fn=_cmd_demo)
    r = sub.add_parser("route", help="route workloads; prints JSON")
    r.add_argument("--assumptions", default=str(CONFIG_DIR / "assumptions.json"))
    r.add_argument("--workloads", default=str(CONFIG_DIR / "workloads.json"))
    r.set_defaults(fn=_cmd_route)
    c = sub.add_parser("calibrate", help="update throughput assumptions from measured runs (CSV)")
    c.add_argument("--samples", required=True)
    c.add_argument("--assumptions", default=str(CONFIG_DIR / "assumptions.json"))
    c.add_argument("--out", default="assumptions.calibrated.json")
    c.set_defaults(fn=_cmd_calibrate)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
