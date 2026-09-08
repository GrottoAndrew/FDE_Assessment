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

**One money representation, everywhere** (ADR-0007): `core.money` is
`numeric(20,6)`, and every monetary value travels with its ISO-4217 code. Floats
do not represent money, and neither do minor-unit integers here — SEC Rule 612
quotes sub-$1 securities in $0.0001 increments, so a 2-decimal minor unit cannot
hold a lawful bid. One type across the store, the API, and the UI means nothing
translates on the way through, and a translation layer is where precision dies.

Serialize as a JSON **string**, never a JSON number: IEEE-754 loses the tail.

Rule 612 increments are enforced on quotations (`md.quote_snapshot.bid`/`ask`)
by `core.is_rule612_increment`. They are deliberately **not** enforced on `last`:
a trade may print sub-penny through price improvement, a quote may not.

`iso.currency.minor_unit` survives for display and settlement rounding. It is no
longer the storage rule.

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
| `bid` / `ask` | best quoted price from the configured source at `as_of_at_utc` | security × snapshot | `md.v_quote_latest` | market data |
| `mid` | `(bid+ask)/2`; **NULL** on a crossed or one-sided book | security × snapshot | `md.v_quote_latest` | market data |
| `spread_abs` | `ask - bid`, in the security's currency | security × snapshot | `md.v_quote_latest` | market data |
| `spread_bps` | `(ask-bid)/mid × 10000`, rounded to 2dp; NULL when `mid` is NULL | security × snapshot | `md.v_quote_latest` | market data |
| `last` | last sale reported by the configured source; **not** an official close | security × snapshot | `md.v_quote_latest` | market data |
| `prev_close` | Orion's reconciled close for a held position (HEU-001); otherwise the source's prior close | security × session | `pos.position_snapshot` → `md.v_quote_latest` | ops |
| `quantity` | reconciled share count **as of `as_of_date`**, never as of today | account × security × date | `pos.position_snapshot` | ops |
| `notional` | `quantity × price`, labeled with **both** as_of values or not returned | account × security | `pos` × `md` | ops |

Undefined here on purpose, and therefore returning ASK-202: `unrealized_pl`
(needs a cost-basis convention — average, FIFO, or tax lot), `volatility`,
`liquidity_score`.

## Source precedence

When two sources disagree, higher wins and the divergence is **reported**, never
silently resolved. Nothing lower ever overwrites something higher.

| rank | source | authoritative for |
|---|---|---|
| 1 | entitled exchange feed *(sprint 2)* | real-time price, size, venue timestamp |
| 2 | clearing firm book of record *(not connected)* | intraday quantity, cash |
| 3 | Orion | reconciled quantity, cost basis, prior close |
| 4 | EDGAR | issuer-disclosed facts, cited by `accession_no` |
| 5 | interim quote source (Yahoo, delayed) | price **only** while rank 1 is absent |
| 6 | public news | attribution only — never a price, never a quantity, never a cause |
| 7 | model inference | never a fact; it composes cited facts or it escalates |

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
