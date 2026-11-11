# Runbook

| Symptom | Likely cause | Action |
|---|---|---|
| `demo` exits 1 | ground truth mismatch, reconciliation failure, or non-idempotent replay | run `python -m unittest discover -s tests -v`; the failing test names the control |
| `BatchConflictError` | same `batch_id` re-sent with different content | give the new content a new batch id; investigate why upstream changed a closed batch |
| `reconcile()` returns failures | manual edit, partial restore, or bug | read each message (it names the batch/table); restore from bronze, which is append-only |
| Quarantine rate jumps | upstream schema drift | group `quarantine_events.reasons`; `*:unexpected_field` means new columns, `*:wrong_type` means type change |
| `BillingError: row N ...` | export columns renamed or empty values | fix the export query; the message names the row and column |
| Router says "No engine meets the SLO" | SLO too tight or data too large | relax the SLO, split the workload, or add larger sizes in config |
| Router flips engines between runs | assumptions changed | expected after `calibrate`; review the diff of `assumptions.json` in the PR |
| Anomaly alert | real spend spike | the explanation names engine, resource, day, baseline and multiple; start with that warehouse/SKU's query history |

## Release checklist

1. `python -W error -m unittest discover -s tests`
2. `python -m routelake demo` and commit refreshed `reports/` and `data/sample/` (a test fails if they are stale)
3. Tag, push, confirm the CI matrix is green.
