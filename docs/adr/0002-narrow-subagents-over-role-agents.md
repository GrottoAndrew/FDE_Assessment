# ADR-0002: Decompose by task, not by job title

Status: accepted
Date: 2026-09-08
Decider: Andrew Nelson
Time spent: 10 min

## Context
The intuitive decomposition mirrors an org chart: a "sales assistant", a
"support agent". Those boundaries are drawn around *people*, and people are
general-purpose. An agent named for a role inherits an unbounded task, which
means an unbounded data scope, an untestable output, and a failure you cannot
localize.

## Decision
Each agent is one verb and one object, stateable in a single line without "and".
`appointment_setting_agent`, `order_tracking_agent`, `refund_eligibility_agent` —
not `sales_assistant`. Enforced mechanically: `AGENT_REGISTRY.yaml` is the only
place agents exist, and `tests/test_contracts.py` rejects conjunctions and vague
role nouns in `single_task`.

## Alternatives considered
| option | why not |
|---|---|
| One capable agent with many tools | Every failure is "the agent was wrong"; nothing to fix and nothing to eval |
| Role-shaped agents (3–5 broad ones) | Data scope becomes the union of everything the role might need — least privilege dies |
| Function-per-tool (one agent per API call) | Too granular; orchestration cost exceeds the work |

## Consequences
**We gain:** each agent gets its own eval cases, its own GRANTs, and a blast
radius bounded by its scope. A failure names itself.
**We lose:** more orchestration surface, more registry entries, and real latency
from multi-hop routing. A single broad agent would be faster to build and
faster at runtime.
**We revisit when:** orchestration overhead exceeds the work being orchestrated.

## Evidence
`tests/test_contracts.py::test_every_agent_has_exactly_one_task`,
`::test_no_vague_agent_names`.
