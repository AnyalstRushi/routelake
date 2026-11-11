# Validating on real Snowflake and Databricks accounts

The local suite proves the logic. This checklist proves it against reality. Use free trials and keep guardrails on.

## 0. Guardrails first
* Snowflake: create a resource monitor with a small credit quota and `SUSPEND` action; set `AUTO_SUSPEND = 60` on every test warehouse.
* Databricks: use a budget alert, small clusters/serverless warehouses, and auto-termination.

## 1. Billing adapters
1. Run `cloud/snowflake/01_export_metering.sql` and `cloud/databricks/01_export_usage.sql`.
2. Save as `snowflake_metering.csv` and `databricks_usage.csv` in a folder.
3. `python -m routelake demo --data <folder>`; confirm record counts match the row counts you exported.
4. Check one day's total against the vendor's own cost UI.

## 2. Calibrate the model
1. Pick 3 representative queries/jobs per kind (sql_bi, batch_etl, ml_training). Run each at 2-3 sizes on each engine.
2. Record `engine,kind,size,scan_gb,runtime_s` (Snowflake: `cloud/snowflake/02_calibration_samples.sql`; Databricks: your query history export).
3. `python -m routelake calibrate --samples samples.csv --out assumptions.calibrated.json`
4. Replace `config/assumptions.json` prices with your contract rates, then `python -m routelake route`.

## 3. Compare prediction and reality
Run the routed workload on the chosen engine and the runner-up. Predicted cost ordering should match billed cost ordering. If it does not, inspect `startup_seconds`, `auto_suspend_seconds` and the scaling exponent first.

## 4. Phase 2: shared Iceberg tables (not included in v1)
The exact DDL depends on your catalog (Unity Catalog, Snowflake Open Catalog/Polaris, Glue). Follow each vendor's current Iceberg guide and keep this repo's contract and reconciliation tests as the acceptance criteria.
