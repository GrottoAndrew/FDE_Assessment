# Data model: canonical joins and ISO vocabulary

Full rationale in [ADR-0003](../adr/0003-canonical-entity-layer-and-iso-codes.md).
DDL in `src/data/schema/`. Apply in numeric order.

## The rule

> **Agents join `core.v_entity_resolved`. Agents never join a raw source table.**

Everything below exists to make that rule safe to follow.

## The canonical join

```
  source systems              canonical layer            read surface
  ──────────────              ───────────────            ────────────
  crm.customer  ──┐
  billing.acct  ──┼──> core.entity_xref ──> core.entity ──> core.v_entity_resolved
  support.org   ──┘     (source_system,      (entity_id,     (excludes merged;
                         source_id,           canonical)      flags provisional
                         match_method,                        fuzzy matches)
                         match_score)
```

`core.entity_xref` carries `UNIQUE (source_system, source_id)` — one source id
resolves to exactly one entity, enforced by the database rather than by
convention. `match_method` and `match_score` make the resolution auditable:
a fuzzy link below 0.90 sets `has_provisional_match` on the view, and agents
must escalate rather than assert on those rows.

Merged duplicates set `merged_into` and clear `is_canonical`; a CHECK constraint
keeps that pair consistent. The view filters `WHERE e.is_canonical`, so a
retired duplicate cannot be cited even by an agent that guesses its id.

This is what turns "which system is right?" from a debate into a query, and it
is the entire job of `discrepancy_agent`.

## ISO vocabulary

| ISO | table | joined from | why it matters here |
|---|---|---|---|
| 3166-1 alpha-2 | `iso.country` | `core.entity.country_code`, `core.account.country_code` | "USA"/"US"/"United States" silently splits a `GROUP BY` into three |
| 3166-2 | `iso.subdivision` | `core.contact.subdivision_code` | region rules for business-hours logic |
| 4217 | `iso.currency` | `core.account.currency_code` | `minor_unit` prevents JPY being divided by 100 |
| 639-1 / 639-3 | `iso.language` | `core.entity.language_code` | response language selection |
| 8601 | *(format, not a table)* | every `timestamptz` / `date` column | UTC storage; no dates in text columns, ever |

ISO-8601 is enforced by type rather than by table:
`tests/test_contracts.py::test_no_text_date_columns` fails the build if any
column matching `*date*`/`*_at*`/`*timestamp*` is declared `text`.

Currency is stored in **minor units** as `bigint` (`core.money_minor`). Floats
do not represent money. Every monetary value travels with its ISO-4217 code —
a bare number is a defect, and `sales_analytics_agent` has a hardcoded rule
saying so.

`core.dim_date` is the conformed date dimension. Every time-series metric joins
it, so "last quarter" resolves identically for every agent — including ISO
week-numbering, where `iso_year` and calendar year legitimately differ in
early January.

## Metric definitions

> **A metric with no definition here does not exist.** `gate_agent` rule
> `ASK-202` returns ASK for any metric absent from this section.

Add each metric before an agent computes it:

| metric | definition | grain | source | owner |
|---|---|---|---|---|
| `revenue` | sum of `sales.order.amount_minor` where `status='fulfilled'` | account × day | `sales.order` | *(TBD sprint day)* |
| *(add on sprint day)* | | | | |

This table is the antidote to the most common demo failure: two agents reporting
different revenue because they filtered differently, and nobody able to say which
is right.

## Ops tables — the guardrails, made observable

| table | written by | read in the readout for |
|---|---|---|
| `ops.hitl_queue` | gate, any escalating agent | what the system refused to guess at |
| `ops.audit_log` | `heuristic_override_agent` | every override, with `rule_id` and before/after |
| `ops.failure_log` | retry exhaustion | what failed loudly instead of silently |
| `ops.handoff_queue` | orchestrators | cross-domain observations noticed but not acted on |
| `ops.flag` | monitoring agents | data-quality issues surfaced |

`ops.failure_log` stores `inputs_hash`, not the inputs. Logs are not a PII sink.
