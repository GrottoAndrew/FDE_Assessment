# The sub-agent contract

Read before adding any agent. An agent that violates this is a liability with a
name, and `tests/test_contracts.py` will reject it.

## 1. One verb, one object

    GOOD  "Return current fulfillment status for one order id."
    BAD   "Handle order inquiries."               <- role, not task
    BAD   "Track orders and notify customers."    <- 'and' means two agents
    BAD   "Smart order assistant."                <- adjective doing the work

The test for whether you have gone narrow enough: can you state the agent's
failure mode in one sentence? "It returns the wrong shipment status" is a task.
"It doesn't help enough" is a role.

## 2. Declare the smallest possible data scope

`data_scope` lists the exact tables. `src/data/schema/003_agent_scopes.sql`
turns each into a Postgres role holding those GRANTs and nothing else, plus RLS
that fails closed when `app.agent_name` is unset.

This is the difference between a boundary and a suggestion. A prompt saying
"only read orders" is advice. A role that cannot `SELECT core.entity` is a
control. Golden case `SCP-501` probes it — if that case passes, the boundary is
decorative.

`gate_agent` has `data_scope: []` on purpose. It decides whether work may
proceed; it must not be able to look at what it is deciding about.

## 3. Write scope is empty by default

Sub-agents propose. The orchestrator commits. One audited write point beats
twelve. The only exceptions are `ops.*` sinks — `hitl_queue`, `audit_log`,
`failure_log`, `flag` — which exist so guardrails are observable.

`email_response_agent` has no write scope and no send tool. It *cannot* send.
That is a structural guarantee, not a behavioral one, and it is worth a sentence
in the readout.

## 4. Prefer a hardcoded rule to model judgment

Every `hardcoded_rules` entry is a decision the model no longer gets to make.
These are deterministic, testable, and free.

    - "Status not in the ISO status enum returns INDETERMINATE, never a guess."
    - "Cite the row id behind every fact. No uncited claims."
    - "Money returns with its ISO-4217 code. A bare number is a defect."

If you find yourself writing "the agent should be careful about X", X is a
hardcoded rule you have not written yet.

## 5. Declare what stops you

`escalate_when` lists the conditions under which the agent returns INDETERMINATE
and writes to `ops.hitl_queue`. Minimum set for any agent:

- a required input is null or unresolvable
- the entity reference matches zero or more than one row
- two sources disagree and the agent cannot tell which is authoritative
- confidence is below threshold on anything with an external side effect

**Escalation is a successful outcome.** An agent that guesses to avoid escalating
is the failure mode this architecture exists to prevent.

## 6. Stay inside your silo

Domain agents report to exactly one orchestrator. An orchestrator that notices
out-of-domain work writes it to `ops.handoff_queue` and drops it — it does not
reason about it, summarize it, or act on it. Golden case `SIL-701` checks that a
sales orchestrator handed off a marketing observation *and did not act on it*.

## Checklist for a new agent

- [ ] `single_task` is one line, one verb, no "and"
- [ ] `data_scope` is the minimum, with a matching role in `003_agent_scopes.sql`
- [ ] `write_scope` is `[]` or `ops.*` only
- [ ] at least one `hardcoded_rules` entry
- [ ] `escalate_when` covers null inputs and ambiguous references
- [ ] one golden case for the happy path, one for the escalation path
- [ ] `make tdd` green
