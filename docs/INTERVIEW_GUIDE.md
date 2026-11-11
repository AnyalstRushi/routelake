# How to present RouteLake (for Analyst Rushi)

Use this to talk about the project in your own words. Run it, break it, change a number, and watch what happens before any interview.

## 30-second pitch
"Most projects show a pipeline on one platform. I built the layer above it: a control plane that validates data with contracts, decides whether each workload should run on Snowflake or Databricks based on cost and SLO, and flags billing spikes. The pipeline logic is tested against planted ground truth, and the cost model is calibratable from real measurements."

## Questions you should be able to answer
1. *Why median/MAD instead of mean and standard deviation?* A spike inflates the mean and the standard deviation, hiding itself. The median barely moves.
2. *Why the ratio gate in the anomaly detector?* A very smooth series has a tiny MAD, so a 10% wobble scored as extreme. A test on 25 spike-free seeds caught it. Statistical significance and business materiality are different gates.
3. *Why hysteresis in the router?* Without it, a 2% saving would move a workload between engines. Migration has a cost the model does not see.
4. *What does idempotency buy you?* Safe retries. Replay is a no-op; same id with different data is an error.
5. *What would you change at 100x scale?* Replace SQLite with Delta/Iceberg tables, make dedup a MERGE keyed by event_id, stream with Structured Streaming, keep contracts as a shared library.
6. *What is not proven?* Say it first: no live-account runs yet; the dollar figures are assumptions; the calibrate command exists to close that gap.
7. *Where did AI help?* Be straightforward. If you used an AI assistant to draft, say so, and be ready to explain every module and modify it live. That ability, not the typing, is what the project demonstrates.

## Five-minute live demo
`python -m unittest discover -s tests` -> `python -m routelake demo` -> open `reports/latest.md` -> change a throughput in `config/assumptions.json` -> `python -m routelake route` and explain why a decision moved.
