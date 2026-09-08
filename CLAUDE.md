# Working rules for this repo

This is a 2.5-hour sprint prototype for an FDE assessment. The clock is the
binding constraint. Read `docs/build_plans/SPRINT_PLAN_150MIN.md` before acting.

## Hard constraints

1. **Stop building at T-120.** The last 30 minutes are the readout. Say so if we
   are approaching it.
2. **Cut scope, never guardrails.** If we are behind, drop agents and features.
   Never drop the gate, the retry policy, the audit log, or the eval run.
3. **Never delete or weaken a failing test to go green.** Mark it `xfail` with a
   reason and surface it. Same for loosening an assertion or a schema.
4. **No secrets in the repo, ever.** `.env` only, referenced via `os.environ`.
5. **No `stub`-mode eval numbers in any summary.** Say "not measured."
6. **Never substitute a default for a failed call.** Return FAILED and write to
   `ops.failure_log`. A plausible partial presented as complete is the worst
   outcome available.

## Before adding an agent

Read `docs/coding/AGENT_CONTRACT.md`. The agent must have:
one-line `single_task` with no "and" · minimum `data_scope` · `write_scope` of
`[]` or `ops.*` · at least one `hardcoded_rules` entry · `escalate_when` covering
null inputs and ambiguous refs · a happy-path golden case and an escalation case.

Then `make tdd`. Contract tests reject a bad registry in 0.1 seconds.

## When something is ambiguous or sensitive

Do not guess and do not silently pick a default. Follow `src/policies/gating.yaml`:
one clarifying question, or BLOCK. Ambiguity resolved by assumption goes in
`docs/build_plans/RISK_REGISTER.md` with the assumption named.

Escalation is a successful outcome, not a failure.

## Sub-agents

Narrow only. If a proposed sub-agent's task needs "and" or a role noun
("assistant", "manager", "helper"), it is two agents or it is wrong. Prefer a
hardcoded deterministic rule over model judgment every time — each hardcoded rule
is a decision the model no longer gets to make, and a line we can point to in the
readout.

Do not spawn sub-agents that are not in `AGENT_REGISTRY.yaml`.

## Data

Agents read `core.v_entity_resolved`, never a raw source table. Enumerable fields
FK to `iso.*`. Timestamps are `timestamptz` UTC. Money is minor units plus its
ISO-4217 code — a bare number is a defect. A metric with no definition in
`docs/coding/DATA_MODEL.md` returns ASK rather than a computed guess.

## Decisions

Any non-obvious choice gets a ≤15-line ADR in `docs/adr/` **at the moment it is
made**, using `ADR-TEMPLATE.md`. Fill in what we gave up — an ADR with no cost is
a preference, not a decision. ADR titles are scraped into the deck prompt
automatically, so writing one is also deck prep.

## Commits

Commit at every green test run: `make tdd && git commit -m "<area>: <change>"`.
Commit the red states too — a history showing red → green is evidence of method.
Never `--force`.

## Communication style

State what is done and what is not. If a step was skipped, say which and why. If
a test fails, show the output. No hedging on completed work, no optimism about
incomplete work. Unfinished scope becomes slide 7 of the readout, not a surprise.
