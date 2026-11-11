# Architecture

## Principles

1. **Explicit over clever.** Every decision (route, quarantine, alert) carries a human-readable reason.
2. **Deterministic.** Same input and seed give byte-identical output. No wall-clock or randomness leaks into logic.
3. **Fail loudly, never silently.** Bad config, bad billing rows and conflicting replays raise typed errors with row numbers.
4. **Portable SQL shapes.** The local engine is SQLite; the table shapes and set-based SQL map directly to Delta/Iceberg tables.

## Data flow

```
events -> bronze_events (append-only, keyed batch_id+seq, payload as JSON text)
       -> contract.validate()
            invalid -> quarantine_events (reasons: "price:below_min,...")
            valid   -> silver_events (typed, UTC-normalised, first-write-wins dedup, is_late flag)
       -> batch_log (received = silver + duplicates + quarantined, always)
silver -> gold_daily_revenue, gold_funnel (full refresh, atomic)
```

### Guarantees

| Guarantee | Mechanism |
|---|---|
| Replaying a batch changes nothing | `batch_log` check; identical content returns `replayed=True` |
| Reusing a batch id with different content is rejected | payload comparison, `BatchConflictError` |
| A crash mid-batch leaves no partial state | one explicit transaction per batch, rollback on any exception |
| Duplicate events collapse deterministically | `INSERT OR IGNORE` on `event_id` (first write wins) |
| Totals add up | `reconcile()`: batch arithmetic, bronze counts, processed flags, silver/quarantine totals, gold-vs-silver revenue |

## Control plane

```
workloads.json + assumptions.json
   -> estimate(workload, engine, size) for every size
   -> best_plan(): cheapest size meeting SLO (else fastest, flagged infeasible)
   -> route(): cheapest feasible engine; keep default if saving < threshold
   -> summarize(): routed vs all-on-each-engine
billing CSVs -> parse_* -> UsageRecord -> daily_series -> detect() -> Anomaly + explanation
measured runs CSV -> calibrate() -> new assumptions (re-validated before writing)
```

## Target physical architecture (roadmap, not in v1)

Ingest with streaming on Databricks into **Apache Iceberg** tables in object storage; Snowflake reads the same tables through an Iceberg catalog integration; the router decides which engine executes each workload. See `cloud/RUN_ON_YOUR_ACCOUNTS.md`.
