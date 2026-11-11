# Limitations (read this before using any number)

## Verified locally
Contract rules, medallion logic, idempotency, atomicity, reconciliation, cost-model arithmetic, routing rules, billing parsing, anomaly detection, calibration round-trip and the CLI. 73 tests on Python 3.12.

## NOT verified
* **No live Snowflake or Databricks execution.** The local engine is SQLite. SQL in `cloud/` is provided for export, and column names follow the vendor documentation as of writing, but must be confirmed in your account.
* **Cost and throughput numbers are assumptions**, not benchmarks and not price quotes.
* **Python 3.10, 3.11, 3.13** are exercised by the CI matrix, not by the local run used for this release.
* **Scale:** SQLite is single-writer and in-process. Nothing here was load-tested beyond thousands of events.
* **Iceberg interoperability** between the two engines is a roadmap item, not implemented.
* **Anomaly detector** is a statistical baseline, not a forecast; strong weekly seasonality needs a seasonal baseline.
* **Billing parsing** takes the calendar date from the timestamp text as written (Snowflake's session time zone), and applies one DBU price unless you pass per-SKU prices.

## Design choices that look like gaps but are deliberate
* No third-party dependencies.
* No LLM in the cost-control path: decisions must be reproducible and explainable.
* First-write-wins dedup: later versions of the same `event_id` are counted as duplicates, not updates.
