# The 150-minute sprint

Everything in this repo exists so that minute 0 is not spent on setup. Read this
once before the sprint; follow it during.

**Hard rule: stop building at minute 120.** The last 30 minutes are the readout,
and a working demo of 60% of the problem beats a broken demo of 90%. Set a timer.

---

## Who writes what

**You are not hand-typing SQL or Python.** That is the slowest possible use of
150 minutes and it is not what is being assessed. The split:

| you produce | I produce |
|---|---|
| The entity map: what things exist, what identifies each, which system owns it | `004_domain.sql` — tables, keys, joins, constraints, FKs into `iso.*` |
| The task list: what jobs a user actually performs | `AGENT_REGISTRY.yaml` entries + the agent implementations |
| The business rules, written **and** unwritten | `gating.yaml` + `heuristics.yaml` entries |
| Metric definitions ("revenue means X, at Y grain") | The queries, and the `DATA_MODEL.md` rows |
| Judgment calls, scope cuts, what to fake | Tests, evals, the DDL, the wiring |

**"No code at T-0→T-10" meant: do not start me generating before the entity map
exists.** Code written against a wrong entity model is worse than no code — you
will spend the back half debugging contradictions instead of building. It never
meant you should be typing.

What you say at T-10 looks like this, not like SQL:

> "Orders live in the ops DB keyed by `order_no`. Customers live in Salesforce
> keyed by `sfid`, and in the billing system keyed by email — those two collide
> about 5% of the time. A rep asks 'where is this order' and 'is this refundable'.
> Refund policy is 30 days written, but corporate cards get 90 in practice."

From that I write the schema, the xref, the two agents, the heuristic, and their
golden cases. **Your job is to be the domain and judgment layer; mine is to be
the typing layer.** If you find yourself writing DDL by hand, stop and describe
it to me instead.

Where you *should* go hands-on: reading the generated schema before it is
applied, reading failing eval cases, and deciding what to cut. Review is where
your time earns the most.

---

## T-0 → T-10 · Frame the problem (specify, don't build)

| do | why |
|---|---|
| Say the problem in one sentence | If you can't, you don't have it yet |
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

## T-40 → T-55 · Guardrails before capability

Adapt `gating.yaml` to the domain's sensitive categories. Elicit heuristics —
ask the interviewer directly: *"what rule do your people follow that isn't in the
policy?"* That question is itself a strong signal, and the answer is slide 5.

Wire retry + `FAIL_LOUD`. Do this **before** building agents: guardrails
retrofitted onto working agents get skipped when the clock runs down.

## T-55 → T-95 · Build agents, narrowest first

Order: the agent that makes the demo work → the agent that makes it *correct*
(`red_team` / `discrepancy`) → the rest.

    make evalq      # after every agent
    make tdd && git commit -m "agents: <name>"

Hardcode aggressively. A hardcoded rule that passes its golden case beats a model
call that probably passes.

## T-95 → T-105 · Debug slot (reserved — do not spend it early)

This block is *pre-committed to being wrong about something*. Every build has one
thing that does not work and takes 3x longer than expected. If you have not
reserved time for it, it eats the readout instead.

    make eval                        # full set, see what actually fails
    .venv/bin/pytest -x -q tests/    # fail fast on the first contract break

Debug order — cheapest signal first:
1. `make tdd` — a structural break shows here in 0.1s
2. `eval_output/<run>/report.md` — every failure lists *why the case exists*
3. `ops.failure_log` / `ops.hitl_queue` — what failed loudly vs. escalated
4. Only then read agent code

If a fix is not landing in 10 minutes: `xfail` the test, write the reason, and
move on. Name it in the readout as a known gap. **Do not spend the ROI or
readout block debugging.**

## T-105 → T-112 · Refactor pass (7 minutes, bounded)

Not a rewrite. A named, timeboxed cleanup with a specific target list:

    /simplify                        # reuse + simplification, quality only

Look for exactly these, in order:
1. **Duplicated logic across agents** → one helper in `src/common/`
2. **A rule living in a prompt that should be in `heuristics.yaml`** — this is
   the one an interviewer will find. Move it.
3. **An agent whose `single_task` grew an "and"** → split it or narrow it
4. **Any hardcoded connection string, table name, or magic number** → `.env` or
   config
5. **Dead scaffolding** from the illustrative sales example

Rule: `make tdd` green before and after. If a refactor breaks a test, revert it —
7 minutes is not enough to fix a regression you introduced on purpose.

## T-112 → T-120 · Full eval and baseline

    make eval
    python3 eval_workflows/run_evals.py --set-baseline

Read `eval_output/<run>/report.md`. A safety-category failure exits 2 — fix it or
say plainly that you are demoing with a known gap.

## T-120 → T-125 · Cost and ROI (5 minutes)

    make cost VOL=5000

Edit the `AGENTS` table in `scripts/cost_model.py` to match the agents you
actually built and their real token profiles (take these from `eval_output/`,
not from guesses). The sensitivity block gives you the four-configuration
comparison for the ROI slide.

What to say, in this order:
1. **Unit cost** — "$X per completed task, measured not estimated"
2. **The lever** — caching the stable prefix beats model routing; the single
   biggest lever is which model the orchestrator runs on
3. **The tradeoff** — moving the orchestrator down is a quality bet you have not
   measured yet, so you did not make it
4. **Break-even** — cost per task vs. the loaded cost of the human minutes it
   replaces. Be conservative and say your assumption out loud.

Do not present a savings percentage you cannot decompose. "70% cheaper" invites
"compared to what?" and you need the answer ready.

## T-125 → T-150 · Readout. Build nothing.

    make deck       # refreshes docs/presentation/PRESENTATION_PROMPT.txt

That file already carries your ADR titles, agent list, live eval numbers, and
open HITL flags. Paste it into Gamma or Claude.

Dry-run once against the clock. Lead with the constraint, not the architecture.
Slide order is in the deck prompt; the two slides people underweight are 7
(what you'd do next, ranked, with reasons) and 8 (risks still open) — those are
where judgment shows, and they cost nothing to prepare because
`RISK_REGISTER.md` already has them.

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
