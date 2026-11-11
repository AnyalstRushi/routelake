-- Export DBU usage for the last 30 days (feeds `routelake` billing adapter).
-- Requires Unity Catalog system tables to be enabled and SELECT on system.billing.usage.
SELECT usage_date,
       workspace_id,
       sku_name,
       usage_unit,
       usage_quantity
FROM system.billing.usage
WHERE usage_date >= date_sub(current_date(), 30)
ORDER BY usage_date;
-- Save as CSV with these exact column names. Rows whose usage_unit is not 'DBU' are skipped on purpose.
-- Dollar prices differ per SKU and contract: pass your own rates in routelake/report.py (USD_PER_DBU) or
-- extend parse_databricks(sku_prices=...). Do not trust the demo's illustrative rate for real decisions.
