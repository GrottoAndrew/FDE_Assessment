# ADR-0006: Synchronous parent→child orchestration, with supervision as its own silo

Status: proposed
Date: 2026-09-08
Decider: Andrew Nelson
Time spent: 10

## Context
An advisor Q&A turn needs a quote, a filing, and a position in one synchronous
response. The scaffold's silo rule enqueues out-of-domain work to
`ops.handoff_queue` and drops it, which would return an empty answer.

## Decision
`advisor_desk_orchestrator` may call *declared* child orchestrators synchronously;
children never call parents, siblings never call each other. `handoff_queue` keeps
its meaning — out-of-domain *observations*, dropped. Supervision is a separate
orchestrator with sole `INSERT` on `ops.flag`, so the desk cannot clear a flag on
its own output.

## Alternatives considered
| option | why not |
|---|---|
| One orchestrator over all agents | unbounded data scope; supervision self-review |
| Strict async silos only | an interactive Q&A turn cannot wait on a queue drain |

## Consequences
**We gain:** a synchronous answer path and separation of duties on compliance.
**We lose:** the silo is no longer enforced by "drop everything foreign" alone; it
now needs a call-graph test, and a parent failure cascades to its children.
**We revisit when:** a fourth domain appears, or a child needs a sibling's output.

## Evidence
Needs `tests/test_contracts.py::test_orchestrator_calls_are_acyclic` and
`::test_only_supervision_writes_ops_flag`. Unwritten as of this ADR — the
decision is proposed, not in force.
