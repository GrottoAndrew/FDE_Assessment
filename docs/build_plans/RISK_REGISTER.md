# Risk register

Open during the sprint. Every ambiguity you resolve by assumption goes here the
moment you resolve it — an assumption you can name is judgment; one you cannot
is a gap someone else finds for you.

## Assumptions made (fill during sprint)

| # | ambiguity | assumption chosen | if wrong | asked? |
|---|---|---|---|---|
| A1 | Third requested sub-agent is garbled ("agent grep Macro News, Agent,") | it is an SEC filings agent (`filing_fact_agent`), since EDGAR is named primary | if it meant positions/quantity, Orion moves from context to critical path | **open — G-17** |
| A2 | Who holds the real-time market-data entitlement | **resolved**: delayed Yahoo quotes behind a hard call budget this sprint; the firm's entitled feed connects in sprint 2 | delayed data cannot answer 'right now'; that class of question is refused, not approximated | ADR-0008 |
| A3 | Source of position quantity | **resolved**: Orion for prior close, live source for current, routed by a hardcoded intent rule; every quantity carries `as_of_date` | a notional mixing the two without both as_of labels is wrong and looks right | HEU-001, ASK-207 |
| A4 | "OSS" in the brief | open/public sources (SEC, FRED, BLS, exchange notices) | licensed newswires make source licensing a blocking prerequisite | **open — G-16** |
| A5 | Price precision vs the money rule | **resolved**: ONE type, `core.money` = `numeric(20,6)`, everywhere; `money_minor` deleted | rounding discipline is now convention, not a type guarantee | ADR-0007 |
| A6 | Silo rule vs synchronous Q&A | declared parent-to-child synchronous calls; `handoff_queue` for observations only | a strictly async silo returns an empty answer for a multi-source question | ADR-0006 |
| A7 | Security identifier | FIGI internally, CIK for issuers; CUSIP only where Orion already licenses it | a ticker-keyed cache eventually returns a dead issuer's price | G-05, G-06 |
| A8 | Scope of the error agent | **confirmed**: `failure_triage_agent` classifies failed runs; crossed/stale/halted detection is hardcoded inside `quote_snapshot_agent` | a data-integrity agent would duplicate rules that are cheaper as CHECKs | QUO-201/202, FAIL-701/702 |
| A9 | Retention vs 50% compaction | raw turn lands in `ops.advisor_interaction` before compaction; compaction applies to working context only | a compacted summary is not the communication a retention rule contemplates | G-13 |
| A10 | Rule 612 tick size | implemented as originally adopted ($0.01 / $0.0001); the 2024 half-cent amendment is **not** implemented | quotes for tick-constrained names would fail the CHECK once that regime is operative | **open — confirm compliance date** |
| A11 | Interim quote source terms of use | prototype-only input with an expiry date; not a commercial redistribution license | the entitled feed is a hard dependency for production, not an upgrade | ADR-0008 |
| A12 | Backend | local Postgres only; Supabase removed from `.mcp.json` and `.env.example` | none for the prototype; hosted deployment is a separate decision | sponsor, 2026-09-08 |
| A14 | Live egress in this environment | **blocked**: 403 CONNECT for sec.gov, data.sec.gov, and both Yahoo hosts | no live pull has run; the poller is proven only against recorded payloads | confirmed by proxy status |
| A15 | bid / ask / spread from the interim source | **unavailable**: the chart endpoint has no quote book; INDETERMINATE is returned rather than an OHLC-derived spread | the desk's headline feature does not work until the entitled feed lands | NVDA-002, ADR-0008 |
| A16 | Adjusted vs raw prices | the chart layout requests split/dividend adjusted prices | a cached prior close silently changes after a split, and nothing here detects it | **open — G-10** |
| A13 | News causality | headlines are candidate links with a stated basis; `news.candidate_link.asserted` is pinned false by CHECK | without a relevancy/reranking model, any asserted cause is a guess wearing a citation | NEWS-501 |

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
