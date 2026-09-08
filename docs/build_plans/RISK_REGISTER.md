# Risk register

Open during the sprint. Every ambiguity you resolve by assumption goes here the
moment you resolve it — an assumption you can name is judgment; one you cannot
is a gap someone else finds for you.

## Assumptions made (fill during sprint)

| # | ambiguity | assumption chosen | if wrong | asked? |
|---|---|---|---|---|
| A1 | Third requested sub-agent is garbled ("agent grep Macro News, Agent,") | it is an SEC filings agent (`filing_fact_agent`), since EDGAR is named primary | if it meant positions/quantity, Orion moves from context to critical path | **open — G-17** |
| A2 | Who holds the real-time market-data entitlement | nobody new; prototype uses delayed data, labeled, entitlement check stubbed but present | a live-quote demo is not lawful to display without it | **open — G-02** |
| A3 | Source of position quantity | Orion, T-1 reconciled, `as_of` carried on every row | T-1 quantity x live price is silently wrong after any intraday trade | **open — G-08** |
| A4 | "OSS" in the brief | open/public sources (SEC, FRED, BLS, exchange notices) | licensed newswires make source licensing a blocking prerequisite | **open — G-16** |
| A5 | Price precision vs `core.money_minor` | prices are `numeric(18,6)`; minor units stay for settled amounts | sub-$1 quotes are unrepresentable under the repo-wide money rule | ADR-0007 |
| A6 | Silo rule vs synchronous Q&A | declared parent-to-child synchronous calls; `handoff_queue` for observations only | a strictly async silo returns an empty answer for a multi-source question | ADR-0006 |
| A7 | Security identifier | FIGI internally, CIK for issuers; CUSIP only where Orion already licenses it | a ticker-keyed cache eventually returns a dead issuer's price | G-05, G-06 |
| A8 | Scope of the error agent | run-failure triage; data-integrity checks are hardcoded rules inside the quote agent | crossed/stale quote detection has no owner | **open — G-12** |
| A9 | Retention vs 50% compaction | raw turn is persisted before compaction; compaction applies to working context only | a compacted summary is not the communication SEA 17a-4 requires | G-13 |

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
