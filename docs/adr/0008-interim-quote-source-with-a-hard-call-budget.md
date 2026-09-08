# ADR-0008: Yahoo delayed quotes as the interim source, behind a hard call budget

Status: accepted
Date: 2026-09-08
Decider: Andrew Nelson
Time spent: 10

## Context
Consolidated real-time quotes need exchange agreements and per-user professional
subscriber reporting. That is a commercial track, and it lands in sprint 2 via
the firm's entitled feed. The prototype still needs prices today, and the free
tier has a hard monthly call cap that a naive fetch-per-request blows in days.

## Decision
Quotes come from a delayed public source, labeled delayed on every row
(`source`, `delay_seconds`, `as_of_at_utc`). Access goes through
`src/common/quote_budget.py`: session-aware TTL (a quote does not change while
the market is closed), symbol dedupe, and monthly pacing across the days
remaining. Exhaustion returns `BUDGET_EXHAUSTED` → the orchestrator returns
FAILED and writes `ops.failure_log`. A cached quote is **never** relabeled as
current. `delay_seconds` is a required column, so switching to the entitled feed
is a config change, not a schema change.

## Alternatives considered
| option | why not |
|---|---|
| Wait for the entitled feed | nothing to demo for a sprint |
| Serve the stale cache when the budget is gone | a plausible partial presented as complete is the failure this system exists to prevent |
| Prefetch a watchlist on a timer | spends the monthly cap on symbols nobody asked about |

## Consequences
**We gain:** a working desk today, and the budget logic survives the vendor swap.
**We lose:** delayed data cannot answer "right now", so the demo has a class of
question it must refuse. The source's terms of use are not a commercial license,
so this path cannot go to production as-is — it is a prototype input with an
expiry date, and the entitled feed is a hard dependency, not an upgrade.
**We revisit when:** the entitled feed connects, or the cap changes.

## Evidence
`tests/test_quote_budget.py` (11 cases, including
`test_exhausted_budget_never_serves_a_stale_quote_as_current`), golden case
`QUO-204`, and `md.quote_call_budget`.
