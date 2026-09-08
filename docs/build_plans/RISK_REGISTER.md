# Risk register

Open during the sprint. Every ambiguity you resolve by assumption goes here the
moment you resolve it — an assumption you can name is judgment; one you cannot
is a gap someone else finds for you.

## Assumptions made (fill during sprint)

| # | ambiguity | assumption chosen | if wrong | asked? |
|---|---|---|---|---|
| A1 | | | | |

## Standing risks in this architecture

| # | risk | likelihood | mitigation in repo | residual |
|---|---|---|---|---|
| R1 | Entity resolution mismatches two records | high | `match_score` + `has_provisional_match`; fuzzy < 0.90 escalates | fuzzy matching is unvalidated on real data |
| R2 | An agent answers outside its scope | medium | GRANTs in `003_agent_scopes.sql`; golden case `SCP-501` | GRANTs only apply if the runtime connects as the agent's role |
| R3 | Heuristic over-fires | medium | positive + negative golden case per rule; `HEU-203` boundary case | rule set is elicited, not derived — it will drift |
| R4 | Retry masks a real failure | low | `FAIL_LOUD`, `ops.failure_log`, exit code 2 | notification depends on a webhook that may be unset |
| R5 | Gate over-blocks and the demo stalls | medium | ASK returns exactly one question and proceeds | ASK rate untuned against real traffic |
| R6 | Prompt injection via a source record | medium | scope + capability limits + `red_team_agent` re-derives from source | not eliminated; layered, not solved |
| R7 | Eval numbers quoted from stub mode | low | `adapter_mode` on every run; report banner | discipline, not enforcement |
| R8 | Sprint overruns and there is no readout | **high** | hard stop at T-120; deck prompt auto-generated | requires you to actually stop |

## Known gaps to state out loud

- No CI, no type checking, no dependency pinning — deliberate under a 150-minute budget.
- Golden set is minimum-viable and synthetic; it measures the harness and the
  guardrails, not real-world accuracy.
- The marketing orchestrator is a stub proving the silo pattern, not a build.
- Integration tests exist at smoke tier only.

Naming these before you are asked converts each from a finding into a decision.
