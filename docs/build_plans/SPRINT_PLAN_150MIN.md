# The 150-minute sprint

Everything in this repo exists so that minute 0 is not spent on setup. Read this
once before the sprint; follow it during.

**Hard rule: stop building at minute 120.** The last 30 minutes are the readout,
and a working demo of 60% of the problem beats a broken demo of 90%. Set a timer.

---

## T-0 → T-10 · Understand and gate (do not write code)

| do | why |
|---|---|
| Write the problem in one sentence in `README.md` under "The problem" | If you can't, you don't have it yet |
| List the entities and their id fields | Determines the canonical layer |
| List the tasks a user actually performs | These become agents, one each |
| Name three things you will **not** build | This is slide 1, and it buys you the rest |
| Ask your clarifying questions **now** | Ten minutes in they are diligence; ninety minutes in they are a rescue |

Ambiguities go in `RISK_REGISTER.md` with the assumption you chose. Say the
assumption out loud in the readout — an assumption you named is judgment; one
you didn't is a gap.

## T-10 → T-25 · Data spine first

    make schema                          # review the DDL
    psql "$DATABASE_URL" -f src/data/schema/001_iso_reference.sql
    psql "$DATABASE_URL" -f src/data/schema/002_canonical.sql

Then map the problem's entities onto `core.entity` + `core.entity_xref`, and add
domain tables in a new `004_domain.sql`. Every enumerable field FKs to `iso.*`.
Every metric you intend to compute gets a row in `DATA_MODEL.md` first.

**Why data before agents:** agents built on an unresolved entity model produce
contradictions you will spend the back half debugging. This is the single
highest-leverage 15 minutes in the sprint.

## T-25 → T-40 · Decompose, and write the golden cases

Fill `AGENT_REGISTRY.yaml`. Keep the four system agents verbatim; replace the
sales examples. For each agent, **before writing it**:

1. one line, one verb, no "and"
2. minimum `data_scope`
3. one golden case for the happy path, one for the escalation path

    make tdd        # contract tests reject a bad registry in 0.1s

**Write the golden cases before the agents.** If you cannot state the right
answer, you do not understand the task yet.

## T-40 → T-60 · Guardrails before capability

Adapt `gating.yaml` to the domain's sensitive categories. Elicit heuristics —
ask the interviewer directly: *"what rule do your people follow that isn't in the
policy?"* That question is itself a strong signal, and the answer is slide 5.

Wire retry + `FAIL_LOUD`. Do this **before** building agents: guardrails
retrofitted onto working agents get skipped when the clock runs down.

## T-60 → T-105 · Build agents, narrowest first

Order: the agent that makes the demo work → the agent that makes it *correct*
(`red_team` / `discrepancy`) → the rest.

    make evalq      # after every agent
    make tdd && git commit -m "agents: <name>"

Hardcode aggressively. A hardcoded rule that passes its golden case beats a model
call that probably passes. Every hardcoded rule is a decision the model no longer
gets to make — and a line you can point to.

## T-105 → T-120 · Full eval and baseline

    make eval
    python3 eval_workflows/run_evals.py --set-baseline

Read `eval_output/<run>/report.md`. A safety-category failure exits 2 — fix it or
say plainly that you are demoing with a known gap. Do not quote a `stub`-mode run.

## T-120 → T-150 · Readout. Build nothing.

    make deck       # refreshes docs/presentation/PRESENTATION_PROMPT.txt

That file already contains your ADR titles, agent list, live eval numbers, and
open HITL flags. Paste it into Gamma or Claude.

Dry-run once against the clock. Lead with the constraint, not the architecture.

---

## Rules that hold when you are behind

- **Cut scope, never guardrails.** A narrow system with a working gate beats a
  broad one that confidently makes things up. Guardrails *are* the differentiator.
- **Cut agents, never evals.** Three agents with a golden set is a stronger
  readout than eight without.
- **Never delete a failing test to go green.** `xfail` it, name it in the readout.
- **Never demo a `stub`-mode eval number.** Say "not measured."
- **At minute 120, stop.** Whatever is unfinished becomes slide 7.

## Recovery: if you are 30 minutes behind at T-90

1. Freeze the agent list at what exists. Add nothing.
2. Run `make evalq` and make the smoke tier pass. Nothing else.
3. Go to the readout at T-115 instead of T-120.
4. Open with: "I timeboxed this at 2.5 hours and prioritized the data spine and
   guardrails over agent count. Here's what that bought and what it cost."

That sentence is a stronger answer than a fourth agent.
