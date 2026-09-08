# ADR-0007: One money type — `core.money` is `numeric(20,6)` everywhere

Status: accepted
Date: 2026-09-08
Decider: Andrew Nelson
Time spent: 8

## Context
The scaffold mandated `bigint` minor units. USD `minor_unit` is 2, and SEC Rule
612 quotes sub-$1 securities in $0.0001 increments, so a lawful $0.1234 bid is
unrepresentable. A second money type would also force a translation step between
the store, the API, and the UI, and translation layers are where precision dies.

## Decision
`core.money` is `numeric(20,6)`, used for every monetary value — quotes, cost
basis, closes, settled amounts. It serializes as a JSON string. Every amount
still carries its ISO-4217 code. Rule 612 increments are CHECK-enforced on
quotations (`bid`, `ask`) via `core.is_rule612_increment`, and deliberately not
on `last`, because a trade may print sub-penny through price improvement while a
quote may not. `minor_unit` survives for display and settlement rounding only.

## Alternatives considered
| option | why not |
|---|---|
| Keep minor units, scale by 10^4 | silently redefines `minor_unit`; breaks every ISO-4217 join |
| Two types: numeric for prices, minor units for settled amounts | a translation boundary and a new defect class, for no gain |
| Float | floats do not represent money |

## Consequences
**We gain:** lawful sub-penny quotes, one representation end to end, no
translation on read.
**We lose:** `numeric` is slower than `bigint` and larger on disk, and we give up
the "money is always an integer" invariant that makes rounding bugs impossible to
write. Rounding discipline is now a convention, not a type guarantee.
**We revisit when:** an instrument quotes in fractions, or a currency needs a
non-decimal increment.

## Evidence
`tests/test_contracts.py::test_exactly_one_money_representation` and
`::test_quote_increments_are_rule612_checked`. `core.is_rule612_increment` in
`src/data/schema/002_canonical.sql`.
