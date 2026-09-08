# ADR-0005: Tribal knowledge is a declarative override layer, not prompt text

Status: accepted
Date: 2026-09-08
Decider: Andrew Nelson
Time spent: 10 min

## Context
Every real operation runs on rules that contradict the written policy. The
canonical shape: policy says refunds stop at 30 days, and CSRs process them
anyway past that window when the order was paid on a corporate card, because the
chargeback and relationship costs both exceed the refund. Buried in a system
prompt, that rule is invisible, untestable, and impossible to show a domain
expert for sign-off.

## Decision
Written policy and unwritten practice live in **separate components**.
`refund_eligibility_agent` applies only the documented rule. `heuristic_override_agent`
runs last, reads `src/policies/heuristics.yaml`, and may supersede the result —
but only via a rule with an id, a named owner, a rationale, and a mandatory
`ops.audit_log` row recording before/after. `HEU-003` is a ceiling rule:
heuristics may loosen business policy and may never loosen a safety gate.
Conflicting matches or null preconditions produce INDETERMINATE and a human
review row — never a default.

## Alternatives considered
| option | why not |
|---|---|
| Encode exceptions in the agent's prompt | Invisible, unversioned, and un-signoff-able |
| Fold exceptions into the written policy | They are not policy; ownership and revocability differ |
| Let the model infer exceptions from examples | Silently generalizes to cases nobody approved |

## Consequences
**We gain:** the override layer is a table a domain expert can review line by
line, every fire is audited, and each rule has a golden case proving it fires
and one proving it declines.
**We lose:** rules must be elicited explicitly — the model will not fill the gap —
and the rule set is a maintenance surface that will drift from practice.
**We revisit when:** the rule set exceeds ~30 entries or conflicts become routine.

## Evidence
`src/policies/heuristics.yaml`, golden cases HEU-201..205,
`tests/test_contracts.py::test_heuristics_cannot_override_a_gate_block`,
`::test_every_heuristic_has_an_owner_and_rationale`.
