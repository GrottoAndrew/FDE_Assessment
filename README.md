# FDE Assessment — multi-agent system scaffold

A problem-agnostic framework for building a constrained multi-agent system in a
2.5-hour sprint. **Nothing here assumes what the problem is.** The domain-specific
pieces are marked as illustrative and are meant to be deleted on sprint day; the
structure, guardrails, and evaluation harness survive any problem statement.

> **Fill this in at T-10:**
>
> ## The problem
> _<one sentence>_
>
> ## Not building
> _1. … 2. … 3. …_

---

## Start here

| you want to | read |
|---|---|
| know what to do minute by minute | [`docs/build_plans/SPRINT_PLAN_150MIN.md`](docs/build_plans/SPRINT_PLAN_150MIN.md) |
| add an agent | [`docs/coding/AGENT_CONTRACT.md`](docs/coding/AGENT_CONTRACT.md) |
| understand the data spine | [`docs/coding/DATA_MODEL.md`](docs/coding/DATA_MODEL.md) |
| know why anything is the way it is | [`docs/adr/`](docs/adr/) |
| present the thing | [`docs/presentation/PRESENTATION_PROMPT.txt`](docs/presentation/PRESENTATION_PROMPT.txt) *(auto-generated)* |

    make preflight  # morning-of checks: key, DB, tests, git, MCP, deck prompt
    make setup      # venv + pytest + pyyaml
    make tdd        # contract tests — 0.1s, no DB, no model
    make eval       # golden set + drift vs baseline
    make deck       # refresh the presentation prompt now

---

## The six design commitments

Each is enforced by a test, not by intention.

### 1. Agents are tasks, not roles
One verb, one object, no "and". `order_tracking_agent`, not `sales_assistant`.
A role-shaped agent inherits an unbounded task, which means an unbounded data
scope, an untestable output, and a failure you cannot localize. Enforced by
`tests/test_contracts.py::test_every_agent_has_exactly_one_task` and
`::test_no_vague_agent_names`. → [ADR-0002](docs/adr/0002-narrow-subagents-over-role-agents.md)

### 2. Orchestrators are siloed
One orchestrator per business domain, and it acts only within it. Out-of-domain
work is written to `ops.handoff_queue` for a sibling orchestrator and dropped —
not summarized, not acted on. A sales orchestrator that notices a marketing
problem records it and moves on.

### 3. Least privilege is a GRANT, not a sentence
Each agent's `data_scope` maps 1:1 to a Postgres role holding exactly those
SELECTs, plus RLS keyed on `app.agent_name` that fails **closed** when unset.
`gate_agent` holds zero data access on purpose. `email_response_agent` has no
write scope and no send tool — it *cannot* send.
→ [`docs/coding/SECURITY_AND_ACCESS.md`](docs/coding/SECURITY_AND_ACCESS.md)

### 4. One canonical entity, ISO vocabulary everywhere
`core.entity` + `core.entity_xref` give every source system's id one resolution
target, so "which system is right?" is a query rather than an argument. Every
enumerable field FKs into `iso.*` — 3166 countries, 4217 currencies with
`minor_unit`, 639 languages, 8601 timestamps enforced by column type. Agents
read `core.v_entity_resolved`, which excludes merged duplicates by construction.
→ [ADR-0003](docs/adr/0003-canonical-entity-layer-and-iso-codes.md)

### 5. Gate first, fail loud
`gate_agent` runs before any work: PROCEED, ASK (exactly one question), or BLOCK,
each attributable to a rule id. Retries are capped at 2 and never applied to
*decisions* — a BLOCK, a permission denial, and an INDETERMINATE are outcomes,
not transient errors. On exhaustion: FAILED, a row in `ops.failure_log` and
`ops.hitl_queue`, a notification, and **no substituted default**.
→ [ADR-0004](docs/adr/0004-gate-first-fail-loud.md)

### 6. Unwritten rules are data
Every operation runs on rules that contradict the written policy — *"refunds stop
at 30 days, but we process corporate cards up to 90."* Those live in
`src/policies/heuristics.yaml`, each with an id, a named owner, a rationale, and
a mandatory audit row — not buried in a prompt where they are invisible and
untestable. `HEU-003` is the ceiling: heuristics may loosen business policy and
may **never** loosen a safety gate.
→ [ADR-0005](docs/adr/0005-heuristics-as-data-not-prompt.md)

---

## Layout

```
docs/adr/              numbered decision records + template
docs/coding/           agent contract, data model, TDD, standards, security
docs/build_plans/      150-min runbook, build-plan template, risk register
docs/presentation/     PRESENTATION_PROMPT.txt  <- auto-generated every 5 turns

src/agents/            AGENT_REGISTRY.yaml — the only place agents exist
src/policies/          gating.yaml · heuristics.yaml · retry.yaml
src/data/schema/       001 iso · 002 canonical · 003 agent scopes (apply in order)
src/orchestrator/      routing + the single commit point per domain

eval_workflows/        golden set, runner, metrics, thresholds
eval_output/           one dir per run + baseline for drift

tests/                 contract tests — the fast red/green loop
scripts/               turn_tick.py (deck prompt) · guard_secrets.py
```

## The four agents that survive any problem

Delete the sales examples on sprint day. Keep these:

| agent | job | why it earns its slot |
|---|---|---|
| `gate_agent` | PROCEED / ASK / BLOCK, before any work | the only thing standing between "under-specified" and "confidently wrong" |
| `red_team_agent` | falsify another agent's claim | defaults to UNSUPPORTED; zero citations is UNSUPPORTED however plausible |
| `discrepancy_agent` | find where two systems disagree | reports the divergence, never silently picks a winner |
| `heuristic_override_agent` | apply the unwritten rules, last | every fire writes `rule_id` + before/after to `ops.audit_log` |

## Evaluation

26 golden cases across four tiers, scoring the guardrails as heavily as the
happy path — gate persistence under user pressure, heuristic boundary
conditions, scope enforcement, fail-loud behavior, and citation sufficiency.

Drift is computed **per case**, not on the aggregate: a run that holds at 23/26
while swapping which three fail is reported as a regression, because it is one.

Safety categories are reported separately and a single failure exits non-zero.
An overall 90% that hides a failed gate test is not a passing system.

    make eval
    python3 eval_workflows/run_evals.py --set-baseline

Runs carry `adapter_mode`. **Never quote a `stub`-mode number** — the harness
ships with a stub adapter so the pipeline is proven before any agent exists, and
the stub deliberately fails the adversarial case so a fresh run cannot show a
misleading 100%.

## The presentation prompt

`docs/presentation/PRESENTATION_PROMPT.txt` regenerates every 5th turn via a
`UserPromptSubmit` hook (`scripts/turn_tick.py`), scraping ADR titles, the agent
list, the latest eval summary, recent commits, and open HITL flags into an
8-slide deck brief. It is never more than 5 turns stale, and it instructs the
generator to say "not measured" rather than estimate any number absent from
`eval_output/`.

    make deck       # force a refresh now

## Sprint guardrails in `.claude/settings.json`

| setting | value | why |
|---|---|---|
| `autoCompactWindow` | `500000` | compaction fires at ~50% of the 1M window instead of ~95%, so context stays cheap and summaries stay accurate |
| `UserPromptSubmit` hook | `turn_tick.py` | the every-5th-turn deck refresh |
| `PostToolUse` hook | `guard_secrets.py` | scans for key shapes on every Write/Edit |
| `permissions.deny` | `curl`, `git push --force`, `.env` reads | the three cheapest ways to lose an interview |

---

## Before the sprint: verify

    make setup && make preflight

`preflight` exits non-zero on anything blocking and prints the fix — a bad API
key, an unreachable database, a dirty tree, a missing deck prompt. If it exits
clean, minute 0 is spent on the problem instead of on setup.
