# RouteLake roadmap

This roadmap separates current local capabilities from future platform work.

## Current implementation
- JSON data contracts and reason-coded quarantine.
- Bronze/Silver/Gold local pipeline with idempotency, transactions and reconciliation.
- Config-driven cost model and SLO-aware router with hysteresis.
- Calibration from measured run inputs.
- Snowflake and Databricks billing-export parsers.
- Median/MAD anomaly detection.

## Next validation milestones
1. Validate billing export SQL and schemas in guarded Snowflake and Databricks trial accounts.
2. Capture measured runtime and billing samples; recalibrate assumptions.
3. Prototype shared Apache Iceberg tables and verify cross-engine reads/writes.
4. Add a scheduler integration only after safe execution semantics are established.

## Longer-term engineering
Operational monitoring, role-based access, masking, backfill controls, deployment automation and production-scale streaming. These are proposals, not current features.
