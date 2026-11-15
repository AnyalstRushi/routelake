# RouteLake — Technical Case Study

**The Intelligence Layer for Data Infrastructure**  
Technical Case Study · 2026 · Analyst Rushi

## Executive summary
RouteLake is a cost-aware lakehouse control-plane prototype. It brings three concerns into one inspectable workflow: contract-driven data quality, workload placement across Snowflake and Databricks, and spend anomaly detection. The current implementation is intentionally local-first and uses Python's standard library with SQLite so that decision logic can be reproduced without cloud credentials.

## Problem statement
Platform teams face three connected questions: where a workload should run given latency and cost constraints; whether incoming records meet explicit data contracts; and whether observed billing contains unusual spend. These concerns are often evaluated independently. RouteLake demonstrates a unified, explainable control layer.

## Design principles
- Explicit decisions with human-readable reason codes.
- Deterministic runs and seeded fixtures.
- Fail loudly on invalid configuration or conflicting batch replays.
- No third-party dependencies in the current implementation.
- Keep cloud integration and physical-table interoperability as separately validated roadmap work.

## Architecture overview
The data plane receives events, writes append-only Bronze records, validates them against a JSON contract, routes invalid records to quarantine, and promotes valid records into typed Silver tables. Gold marts are built with reconciliation checks. The control plane reads workload catalog and cost assumptions, estimates engine/size candidates, selects the lowest-cost SLO-feasible plan, and applies hysteresis. Billing exports are normalized and analyzed using robust median/MAD baselines.

## Data quality and medallion processing
The repository's deterministic generator seeds 5,150 records with known defects. The deck and README report 200 quarantined records, 150 duplicates dropped, and 100 late events flagged. The exact defect categories in the source deck include missing user id, negative price, unknown event type, bad timestamp, and zero quantity. Quarantine retains machine-readable reason codes.

## Reliability properties
- Identical batch replay is a no-op; reusing a batch id with different content is rejected.
- A transaction rollback prevents partial state after a simulated mid-batch failure.
- Reconciliation checks batch arithmetic, processed flags, row counts and Gold-versus-Silver revenue.
- First-write-wins deduplication is deterministic.
- The project reports 73 tests, including end-to-end CLI, fault injection, tamper detection and freshness checks.

## Cost model and workload routing
The cost model exposes startup, scan throughput, minimum billed duration, idle tail, concurrency/cluster count and configured unit rates. The router compares candidate plans, filters by latency SLO, chooses the least expensive feasible option and uses a savings threshold/hysteresis to avoid frequent route changes.

The presentation reports an illustrative scenario of $171.64 per day for the routed mix versus $283.85 per day if all workloads run on Snowflake, a 39.5% modeled reduction. These values are derived from `config/assumptions.json` and are not vendor quotes, measured production savings or independent benchmarks. Calibration with measured runs is required before using the model for decisions.

## Billing anomaly detection
Snowflake `WAREHOUSE_METERING_HISTORY` and Databricks `system.billing.usage` exports are normalized into a common usage shape. The detector uses median and median absolute deviation, combined with robust-score, absolute-dollar and ratio gates. The deck's examples are planted fixture anomalies, not live billing events.

## What is implemented versus planned

| Area | Status | Evidence / boundary |
|---|---|---|
| Contracts, Bronze/Silver/Gold, quarantine | Implemented locally | Python + SQLite; tests and deterministic fixture data |
| Cost model, SLO router, hysteresis | Implemented locally | Config-driven; illustrative rates; calibration available |
| Billing adapters, anomaly detector | Implemented locally | Parses exports / fixture-shaped records; no live account execution |
| Live Snowflake and Databricks execution | Not yet validated | Cloud SQL/export guidance exists; actual execution remains future work |
| Shared Apache Iceberg layer | Roadmap | Documented target architecture, not implemented |
| Production-scale streaming | Roadmap | SQLite prototype is not load-tested beyond thousands of events |

## Limitations and responsible interpretation
- SQLite is an in-process, single-writer local engine; the project has not been load-tested at production scale.
- No live Snowflake or Databricks execution has been validated.
- Cost and throughput rates are assumptions, not vendor pricing or benchmark results.
- The anomaly detector is a statistical baseline, not a seasonal forecast.
- Shared Iceberg interoperability and streaming scale are roadmap items.

## Reproducibility
From the repository root with Python 3.10 or later:

```bash
python -m unittest discover -s tests -v
python -m routelake demo
python -m routelake route
```

## Roadmap
1. Validate export queries and run guarded trial-account workloads against live Snowflake and Databricks accounts.
2. Capture measured runs and recalibrate cost assumptions automatically.
3. Implement a shared Apache Iceberg physical layer and validate cross-engine reads/writes.
4. Add scheduler integration only after routing decisions have safe execution semantics.
5. Add operational monitoring, permissions, backfill controls and runbooks before production claims.

## Open-source project positioning
RouteLake is presented as an engineering prototype and reproducible reference implementation. Its value is the explicit connection between data correctness, workload placement and cost observability—not a claim that it is already a production cloud control plane.
