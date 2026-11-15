# RouteLake presentation assets

The executive presentation and technical case study are maintained as companion portfolio artifacts to the repository.

## Recommended repository placement

- `docs/RouteLake_2026_Technical_Case_Study.md` — version-controlled technical narrative (source of truth for implementation boundaries).
- `presentations/RouteLake_2026_Executive_16_Slides.pptx` — editable executive deck.
- `docs/RouteLake_2026_Technical_Case_Study.docx` — editable document edition.

The editable PPTX and DOCX are currently supplied as companion deliverables. The Markdown case study remains in this repository so the technical content is reviewable in GitHub diffs.

## Presentation narrative

1. RouteLake thesis and product framing.
2. The operating problem: trust, placement and spend.
3. Two-plane architecture and feedback loop.
4. Data contracts and quarantine outcomes.
5. Medallion processing and replay safety.
6. Cost model assumptions and formula.
7. SLO-aware routing and hysteresis.
8. Billing normalization and anomaly detection.
9. Deterministic evidence and test strategy.
10. Reproducible local demo.
11. Implemented capabilities versus roadmap.
12. Limitations and validation boundaries.
13. Open-source operating model.
14. Live-account validation plan.
15. Iceberg and orchestration roadmap.
16. Closing thesis and project links.

## Accuracy rule

The deck must distinguish the local Python/SQLite implementation from live cloud integrations. The 39.5% modelled cost difference is illustrative, not measured savings or a vendor benchmark. Do not describe Apache Iceberg interoperability, production streaming or live Snowflake/Databricks execution as shipped.
