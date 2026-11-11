# Cost model

```
runtime_s   = startup_s + scan_gb / (gb_per_min_per_unit * units**exp) * 60
idle_tail_s = min(auto_suspend_s, max(0, avg_gap_s - runtime_s)),  avg_gap_s = 86400 / runs_per_day
billed_s    = max(min_billed_s, runtime_s) + idle_tail_s
clusters    = ceil(concurrency / max_concurrency_per_cluster)
cost_run    = billed_s / 3600 * units * clusters * usd_per_unit_hour
daily       = cost_run * runs_per_day          monthly = daily * 30
```

`units` is credits/hour (Snowflake sizes XS..XL = 1,2,4,8,16) or DBU/hour (Databricks sizes). `exp` (default 0.85) models sub-linear scaling: doubling the cluster less than halves runtime.

## Why each term exists

| Term | Real-world effect it captures |
|---|---|
| `startup_s` | Interactive BI favours engines that resume in seconds; big batch does not care |
| `min_billed_s` | Short queries still pay a minimum |
| `idle_tail_s` | Auto-suspend keeps billing after the job; frequent jobs share the tail |
| `clusters` | High concurrency forces multi-cluster scale-out |
| `exp < 1` | Bigger is faster but not proportionally; the cheapest feasible size is not always the smallest |

## Decision rule

1. For each engine, choose the cheapest size that meets the SLO. If none does, report the fastest and mark it infeasible.
2. Choose the cheapest feasible engine.
3. **Hysteresis:** if the cheapest engine is not the default and saves less than `min_savings_pct_to_route` (default 10%), keep the default. This avoids migrating workloads for noise.
4. If nothing meets the SLO, the decision says so explicitly. It never pretends.

## What the numbers are

`config/assumptions.json` holds **illustrative** rates and throughputs, encoding a hypothesis: Snowflake wins short, concurrent BI (fast resume); Databricks wins heavy batch and ML (cheaper per unit of throughput). The hypothesis may be wrong for your data. That is why `calibrate` exists: measure, feed it back, re-run.

## Known simplifications

Per-run time is deterministic (no variance or spill), storage and egress are excluded, serverless vs classic pricing is collapsed into one all-in rate per engine, and one workload maps to one engine (no splitting stages across engines).
