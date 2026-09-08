# ADR-0003: One canonical entity table; ISO code tables for every enumerable field

Status: accepted
Date: 2026-09-08
Decider: Andrew Nelson
Time spent: 15 min

## Context
Multi-agent systems produce contradictions for a boring reason: two agents read
two source systems, each holding a different row for the same real-world thing,
and both answer confidently. Layered on top, free-text enums ("USA" / "U.S." /
"United States"; "$" / "USD") turn a `GROUP BY` into a silent double-count. Both
failures survive a demo and surface in the Q&A.

## Decision
`core.entity` holds one row per real-world thing with a surrogate `entity_id`.
`core.entity_xref` maps every source system's id onto it with a match method and
score. Agents join `core.v_entity_resolved`, never a raw source table — the view
excludes merged duplicates by construction, so a stale row cannot be cited even
by guessing its id. Every enumerable field is an FK into `iso.*`: 3166-1
countries, 3166-2 subdivisions, 4217 currencies (with `minor_unit`), 639
languages. Timestamps are `timestamptz` in UTC; ISO-8601 is enforced by type,
not by convention.

## Alternatives considered
| option | why not |
|---|---|
| Let each agent read its own source system | Guarantees the contradiction this exists to prevent |
| Resolve conflicts in the prompt | Non-deterministic, untestable, invisible in an audit |
| Free-text enums plus a normalization step | Normalization gets skipped exactly once, and that's the demo |

## Consequences
**We gain:** `discrepancy_agent` becomes a query rather than an argument. Money
always carries its currency. "Last quarter" means one thing system-wide.
**We lose:** entity resolution must run before anything works — real setup cost
in a 2.5-hour budget, and fuzzy matches below 0.90 need human review rather than
silent acceptance.
**We revisit when:** the source systems already share a canonical id.

## Evidence
`src/data/schema/001_iso_reference.sql`, `002_canonical.sql`,
`tests/test_contracts.py::test_canonical_view_excludes_merged_entities`,
`::test_no_text_date_columns`, golden case `DSC-303`.
