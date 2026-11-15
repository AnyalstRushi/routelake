# RouteLake — Technical Case Study

**The Intelligence Layer for Data Infrastructure**  
Engineering case study · 2026 · Analyst Rushi

## Executive summary

RouteLake is a cost-aware lakehouse control-plane prototype. It combines three inspectable concerns: contract-driven data quality, workload placement across Snowflake and Databricks, and spend anomaly detection. The current implementation is local-first and uses Python's standard library with SQLite so its decision logic can be reproduced without cloud credentials.

## Operating problem

Data teams are asked to deliver reliable analytics while managing different execution engines and fragmented consumption billing. Three questions are connected but often handled separately:

1. Can incoming records be trusted before they affect downstream marts?
2. Which engine and size are the lowest-cost candidates that still satisfy the workload latency SLO?
3. Is observed spend materially different from its historical baseline, and what workload explains it?

RouteLake places these questions in one reference control plane. It does not currently migrate production workloads or execute against live vendor accounts.

## Architecture

### Data plane

Event sources feed append-only Bronze records. A JSON contract validates records and sends invalid payloads to quarantine with machine-readable reason codes. Valid records are normalized and deduplicated into Silver; Gold marts are produced with reconciliation checks.

### Control plane

A workload catalog and configurable assumptions feed a cost model. Candidate engine/size plans are evaluated against latency constraints; the router selects the lowest-cost feasible plan and applies hysteresis to avoid unstable changes. Billing exports from both platforms are normalized into a common usage shape and evaluated by a median/MAD anomaly detector.

## Deterministic data-quality evidence

The supplied deterministic fixture reports 5,150 input records, 200 quarantined records, 150 duplicates removed and 100 late events flagged. The source deck lists five planted quarantine classes: missing user id, negative price, unknown event type, bad timestamp and zero quantity (40 records each). These are local fixture outcomes, not a production ingestion benchmark.

Reliability properties reported by the project include idempotent identical batch replay, rejection of conflicting batch-id reuse, transaction rollback under injected failure, deterministic first-write-wins deduplication and reconciliation of batch arithmetic and Gold aggregates.

## Cost model and routing

The model includes startup time, scan throughput, a sub-linear scaling term, minimum billed duration, idle tail, concurrency/cluster count and configured unit rates. Candidate plans are filtered by the latency SLO before cost comparison. A savings threshold/hysteresis prevents route flapping.

The source presentation reports an illustrative scenario of $171.64/day for the routed mix versus $283.85/day for an all-Snowflake baseline (39.5% modeled difference). This is generated from repository assumptions; it is not vendor pricing, a measured saving or an independent benchmark. The calibration workflow must be populated with measured account runs before operational decisions rely on these values.

## Spend anomaly detection

Snowflake `WAREHOUSE_METERING_HISTORY` and Databricks `system.billing.usage` exports are normalized to a shared record shape. The detector uses a median and median absolute deviation baseline plus robust-score, absolute-dollar and ratio gates. The source deck's anomaly examples are planted fixture events, not live customer incidents. This is a statistical baseline, not a seasonal forecast.

## Implementation status

| Capability | Status | Evidence boundary |
|---|---|---|
| Contracts, quarantine, medallion pipeline | Implemented locally | Python + SQLite, deterministic fixtures and tests |
| Cost model, SLO router, hysteresis | Implemented locally | Config-driven model; assumptions require calibration |
| Billing parsers and anomaly detector | Implemented locally | Export-shaped inputs and planted fixtures |
| Live Snowflake / Databricks execution | Not validated | Requires guarded trial-account runs |
| Shared Apache Iceberg tables | Roadmap | Cross-engine reads/writes not implemented |
| Production-scale streaming | Not validated | SQLite prototype; no production load claim |

## Limitations

- SQLite is an in-process, single-writer local engine.
- No live Snowflake or Databricks execution has been validated.
- Cost and throughput values are illustrative assumptions, not vendor quotes.
- The anomaly detector is not a seasonality-aware forecasting system.
- Shared Iceberg interoperability, scheduler integration and production operations are roadmap work.

## Reproducibility

From the repository root with Python 3.10+:

```bash
python -W error -m unittest discover -s tests -v
python -m routelake demo
python -m routelake route
python -m routelake anomalies
```

## Roadmap

1. Validate export schemas and SQL against guarded Snowflake and Databricks trial accounts.
2. Capture measured runtime and billing samples; calibrate assumptions.
3. Prototype shared Apache Iceberg tables and test cross-engine reads/writes.
4. Add scheduler integration only after routing decisions have safe execution semantics.
5. Add identity, RBAC, monitoring, backfill controls and operational runbooks before production claims.

## Positioning

RouteLake is a reproducible engineering prototype and open-source reference implementation. Its contribution is the explicit connection between data correctness, workload placement and cost observability—not a claim that it is already a production cloud control plane.
