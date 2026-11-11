# Data contracts

A contract is JSON (`contracts/events_v1.json`). Field types: `string`, `number`, `integer`, `timestamp`. Rules: `required`, `enum`, `min`, `max`, `min_length`. `additional_fields` is `reject` (strict, default) or `allow`.

## Reason codes

| Code | Meaning |
|---|---|
| `<field>:missing` | required field absent or null |
| `<field>:wrong_type` | wrong type (booleans are not numbers; 2.0 is not an integer; NaN/inf rejected) |
| `<field>:below_min` / `above_max` | numeric bound violated |
| `<field>:not_in_enum` | value outside allowed set |
| `<field>:too_short` | string shorter than `min_length` after trimming whitespace |
| `<field>:bad_timestamp` | not parseable ISO-8601 (naive timestamps are treated as UTC) |
| `<field>:unexpected_field` | field not in contract (strict mode) |
| `record:not_an_object` | the record is not a JSON object |

A record can carry several codes; they are stored comma-separated in `quarantine_events.reasons` so quarantine can be analysed by reason.

## Evolving a contract

Add a new file (`events_v2.json`) rather than editing v1. Run both in parallel on a sample and compare quarantine rates before cutting over.

## Late data

A valid event whose `ingest_ts - event_ts` exceeds 48 hours (configurable) is kept and flagged `is_late = 1`; it is never dropped.
