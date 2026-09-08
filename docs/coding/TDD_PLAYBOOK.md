# TDD in a 150-minute sprint

Full TDD on everything will cost you the sprint. The move is to be strict where
tests are nearly free and loose where they are not.

## Three layers, three economics

| layer | file | cost | discipline |
|---|---|---|---|
| **Contract tests** | `tests/test_contracts.py` | ~0.1s, no DB, no model | **Strict TDD.** Write the assertion before the YAML. |
| **Golden set** | `eval_workflows/golden/golden_set.jsonl` | seconds, no model in stub mode | **Test-first.** Write the case before the agent. |
| **Integration** | live adapter | slow, non-deterministic | **Test-after.** Smoke tier only. |

Contract tests assert the *shape* of the system: every agent has one task, every
heuristic has an owner, no gate can be overridden. They caught two real defects
in this repo's own registry within a minute of being written. That is the whole
argument for them.

## The loop

    make tdd        # contract tests only, -x, fails in 0.1s
    make evalq      # smoke tier
    make eval       # full golden set + drift vs baseline

## Red → green, per agent

1. **Red — write the golden case first.** Before writing an agent, add its case
   to the golden set with a populated `why`. If you cannot state what the right
   answer is, you do not yet understand the task well enough to build it.
2. **Red — add its contract assertion.** New agent → does it have one task, a
   data scope, a bounded write scope? The existing parameterized tests cover this
   automatically once it is in the registry.
3. **Green — narrowest thing that passes.** Hardcode. A hardcoded rule that
   passes its case beats a model call that probably passes.
4. **Refactor only if a second case demands it.** One case never justifies
   generalization.

## Rules that hold under time pressure

- **Never delete a failing test to go green.** Mark it `xfail` with a reason and
  say so in the readout. A removed test is a lie; an `xfail` is a known gap.
- **Never loosen an assertion to pass.** `retry.yaml` bans retry-with-loosened-schema
  for exactly this reason; the same discipline applies to you.
- **A safety-category failure blocks the demo.** `run_evals.py` exits 2 and says
  so. 24/26 overall is fine; 24/26 with a failed gate test is not.
- **Baseline early.** `--set-baseline` right after the first green run. Drift is
  computed per case, so a run that stays at 88% while swapping which cases fail
  is correctly reported as a regression.

## What NOT to test in the sprint
Prompt wording, model phrasing, latency micro-optimizations, anything requiring
a live external service to assert. Say out loud in the readout that you skipped
these and why — a stated gap reads as judgment; a discovered one reads as an
oversight.
