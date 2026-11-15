# RouteLake roadmap

This roadmap is intentionally evidence-led. Items below are not implemented unless explicitly listed as current local capabilities.

## Current local implementation
- JSON data contracts and reason-coded quarantine.
- Bronze/Silver/Gold local pipeline with idempotency, transactions and reconciliation.
- Config-driven cost model and SLO-aware router with hysteresis.
- Calibration inputs for replacing assumptions with measured runs.
- Snowflake and Databricks billing-export parsers.
- Median/MAD anomaly detection.
- Local CI and deterministic test suite.

## Milestone 1 — Account-level validation
- Validate export schemas and SQL in guarded trial accounts.
- Record measured runtime, bytes scanned, concurrency and billed duration.
- Calibrate workload assumptions from observed data.
- Document credentials, permissions and teardown boundaries without committing secrets.

## Milestone 2 — Shared physical data layer
- Prototype Apache Iceberg tables with an explicit catalog.
- Verify snapshot, schema evolution and time-travel behavior.
- Validate cross-engine reads/writes rather than assuming interoperability.
- Add integration tests and compatibility matrix.

## Milestone 3 — Safe orchestration
- Introduce a scheduler adapter only after route decisions have safe execution semantics.
- Add dry-run, approval gates, idempotency keys and rollback/compensation behavior.
- Keep the cost router advisory until the execution adapter is validated.

## Milestone 4 — Production readiness
- Identity and least-privilege RBAC.
- Secrets management and audit trails.
- Backfill, retry and failure-recovery runbooks.
- Load tests, service-level objectives, monitoring and alert routing.
- Shared state/catalog services suitable for multi-worker operation.

## Explicit non-goals for the current release
- Claiming live cloud execution.
- Claiming production-scale streaming.
- Presenting illustrative savings as measured ROI.
- Treating roadmap integrations as shipped features.
