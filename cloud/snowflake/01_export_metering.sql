-- Export warehouse credit usage for the last 30 days (feeds `routelake` billing adapter).
-- Needs a role with access to the SNOWFLAKE database (ACCOUNT_USAGE schema).
-- ACCOUNT_USAGE views lag real time by up to a few hours, so do not alert on "today".
SELECT START_TIME,
       END_TIME,
       WAREHOUSE_NAME,
       CREDITS_USED_COMPUTE,
       CREDITS_USED_CLOUD_SERVICES,
       CREDITS_USED
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE START_TIME >= DATEADD('day', -30, CURRENT_TIMESTAMP())
ORDER BY START_TIME;
-- Save the result as CSV with these exact column names, then:
--   python -m routelake demo --data <folder holding snowflake_metering.csv>
