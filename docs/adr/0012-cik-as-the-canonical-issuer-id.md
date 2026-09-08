# ADR-0012: CIK is the canonical issuer id; synonyms live in their own table

Status: accepted
Date: 2026-09-08
Decider: Andrew Nelson
Time spent: 12

## Context
`core.entity.entity_id` was `uuid DEFAULT gen_random_uuid()`. The same company
ingested twice becomes two entities, and nothing about the id says otherwise.
Advisors also type company names a dozen ways, and a name column cannot hold
them all without losing which one is canonical.

## Decision
`entity_id` is `text` with a shape CHECK by `entity_type`: an issuer's id **is**
its 10-digit SEC CIK; persons, organizations, and assets carry `PER-`/`ORG-`/
`AST-` prefixes. `md.security.cik` is CHECK-tied to `entity_id` so two columns
cannot hold one identity and drift. Securities stay keyed on FIGI: one CIK has
many securities. Name variants — legal, short, ticker, exchange-qualified,
misspelling, phonetic — live in `core.entity_synonym` with a kind, a source, and
a confidence, plus a generated `synonym_norm` for case- and punctuation-folded
lookup. `core.resolve_entity(text)` returns every match with `is_provisional`
(<0.90) and `is_ambiguous`, so the caller decides; `core.v_synonym_collision`
surfaces any string resolving to two entities.

## Alternatives considered
| option | why not |
|---|---|
| Keep UUIDs, put CIK in xref | the id stays unreadable and duplicate-prone; the check becomes a join |
| One id scheme for all entity types | would mean inventing CIKs for households — a fabricated identifier in the canonical table |
| Synonyms as an array on core.entity | no per-variant confidence, no source, not indexable, not auditable |

## Consequences
**We gain:** a canonical id you can read and verify, resolution that reports its
own confidence, and misspellings that resolve without ever resolving silently.
**We lose:** a natural key is not opaque, so a CIK reassignment or a bad-data
correction becomes an UPDATE cascading across six tables instead of a no-op.
Text keys are also wider than uuid in every index. And the id is now uniform in
*type* but not in *scheme*, which is a thing to explain rather than a thing to
show.
**We revisit when:** non-US issuers arrive without a CIK (LEI is the candidate),
or an entity type needs an id the shape CHECK cannot express.

## Evidence
`src/data/schema/005_cik_canonical.sql`, `tests/test_schema_live.py` (10 cases
against a live instance), `scripts/db_report.sql` sections 1, 2, 7, 8.
Applying it live is what found the `ops.flag` dependency that reading the DDL
missed, and the two views that made the migration non-idempotent.
