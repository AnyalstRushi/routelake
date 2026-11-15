# RouteLake presentation pack

This folder documents the executive presentation that accompanies the RouteLake technical project.

## Executive deck

**RouteLake 2026 — Executive Project Walkthrough**  
16 editable slides covering:

1. Project thesis and operating problem
2. Why data trust, workload placement and spend belong together
3. Reference architecture and control/data planes
4. Bronze → contract gate → Silver → Gold pipeline
5. Data-quality controls, quarantine and idempotency
6. Workload catalog, cost model and SLO-aware routing
7. Snowflake / Databricks candidate comparison
8. Billing normalization and anomaly detection
9. Deterministic demo evidence and test strategy
10. Illustrative cost scenario and its assumptions
11. Failure modes, maturity boundaries and limitations
12. Roadmap and validation plan

The deck is an executive narrative, not proof of live cloud integration. The current code is a local Python + SQLite prototype. The modeled cost scenario is illustrative and must be calibrated against measured account data.

## Technical companion

- [Technical case study — Markdown](../docs/RouteLake_2026_Technical_Case_Study.md)
- [Architecture](../docs/ARCHITECTURE.md)
- [Limitations](../docs/LIMITATIONS.md)
- [Roadmap](../docs/ROADMAP.md)

## Artifact placement

The editable PPTX and DOCX companion files have been generated and supplied separately with the RouteLake 2026 deliverables. They are not yet committed as binary files in this repository. When adding them, use these canonical paths:

- `presentations/RouteLake_2026_Executive_16_Slides.pptx`
- `docs/RouteLake_2026_Technical_Case_Study.docx`

Keep the Markdown case study as the reviewable source of truth for technical claims and implementation boundaries.
