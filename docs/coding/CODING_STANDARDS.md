# Coding standards (sprint edition)

Optimized for a build that will be read aloud in 10 minutes, not maintained for
10 years. Where those conflict, readability at the readout wins.

## Non-negotiable

1. **No secrets in the repo.** `.env` is gitignored; `guard_secrets.py` runs as a
   `PostToolUse` hook on every Write/Edit and scans for key shapes. A leaked key
   in a demo repo is the one unforced error that ends an interview.
2. **No silent defaults.** Substituting a fallback for a failed call is the
   highest-cost bug in an agent demo, because it is invisible until questioned.
   Return FAILED. See `src/policies/retry.yaml`.
3. **Every fact carries a citation.** Agent output includes the row id it came
   from. `metrics.py` enforces `must_cite` on every golden case regardless of
   assertion mode — an answer that is right for unverifiable reasons still fails.
4. **Config is data, not code.** Agents, gates, heuristics, retry — all YAML,
   all under `tests/test_contracts.py`. If the readout needs you to explain
   behavior, you should be pointing at a file, not scrolling through a prompt.
5. **Timestamps are `timestamptz` in UTC.** Format at the edge, never in storage.

## Structure

```
src/orchestrator/   routing + the single commit point per domain
src/agents/         AGENT_REGISTRY.yaml is the only place agents exist
src/policies/       gating / heuristics / retry — behavior as data
src/data/schema/    DDL, applied in numeric order
src/common/         shared types, db access, logging
```

## Style

- Python 3.11+, type hints on function signatures, stdlib first.
- Functions do one thing; if the docstring needs "and", split it. Same rule as
  the agents — see `AGENT_CONTRACT.md`.
- Comment the **why**, never the **what**. `# increment counter` is noise;
  `# fuzzy matches below 0.90 are provisional, so we escalate rather than assert`
  is the thing you will be asked about.
- Errors carry context: `f"agent={name} step={step} run={run_id}: {err}"`.
- No bare `except:`. Catch what you can handle; let the rest fail loudly.

## Git during the sprint

- Commit at every green test run. `make tdd && git commit` is one motion.
- Message format: `<area>: <what changed>` — `gate: add ASK-206 for null tz`.
- Commit the failures too. A commit history that shows red → green is evidence
  of method; a single "initial commit" at minute 148 is not.
- Never `--force`. It is in the settings deny list.

## What to skip on purpose

Type checking, linting configs, CI, dependency pinning, docstrings on every
function, abstract base classes for two implementations. Skipping these is a
defensible choice under a 150-minute budget. Not *knowing* you skipped them is
not — put them on the "with another week" slide.
