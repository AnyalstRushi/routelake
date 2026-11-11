-- Measured runs for `python -m routelake calibrate` (columns: engine,kind,size,scan_gb,runtime_s).
-- Tag the benchmark queries first:  ALTER SESSION SET QUERY_TAG = 'routelake_bench:batch_etl';
SELECT 'snowflake'                                   AS engine,
       SPLIT_PART(QUERY_TAG, ':', 2)                 AS kind,
       WAREHOUSE_SIZE                                AS size_label,   -- map to XS/S/M/L/XL in config
       BYTES_SCANNED / POWER(1024, 3)                AS scan_gb,
       TOTAL_ELAPSED_TIME / 1000.0                   AS runtime_s
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE QUERY_TAG LIKE 'routelake_bench:%'
  AND EXECUTION_STATUS = 'SUCCESS'
  AND START_TIME >= DATEADD('day', -7, CURRENT_TIMESTAMP());
-- WAREHOUSE_SIZE is returned as e.g. 'X-Small'; rename to the config labels before calibrating.
