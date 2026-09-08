# ADR-0007: Quote prices use numeric(18,6); minor units stay for settled amounts

Status: proposed
Date: 2026-09-08
Decider: Andrew Nelson
Time spent: 8

## Context
`DATA_MODEL.md` mandates money as `bigint` minor units with an ISO-4217 code.
USD has `minor_unit = 2`. Sub-$1 equities quote in $0.0001 increments under Rule
612, so a $0.1234 bid is unrepresentable. A repo-wide rule is wrong for this
domain.

## Decision
Quote and price columns are `numeric(18,6)` carrying an ISO-4217 code alongside.
Settled and booked amounts (cash, cost basis, realized P/L) keep
`core.money_minor`. The ISO-4217 code requirement is unchanged everywhere — a
bare number is still a defect.

## Alternatives considered
| option | why not |
|---|---|
| Scale minor units by 10^4 | silently redefines `minor_unit`; breaks every ISO join |
| Float prices | floats do not represent money; non-starter |

## Consequences
**We gain:** correct sub-penny quotes, and one honest rule instead of a rounding
convention nobody documents.
**We lose:** two money representations in one schema, so every agent must know
which one it holds. Mixing them is now a possible defect class that did not exist.
**We revisit when:** the domain adds instruments quoted in fractions (some fixed
income) or a currency with a non-decimal increment.

## Evidence
Needs a contract test asserting no price column is declared `bigint` and no
settled-amount column is declared `numeric`. Unwritten — decision is proposed.
