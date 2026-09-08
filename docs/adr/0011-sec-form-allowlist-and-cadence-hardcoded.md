# ADR-0011: The EDGAR form allowlist and the poll cadence are HARDCODED

Status: accepted — **HARDCODED, pending client decision**
Date: 2026-09-08
Decider: Andrew Nelson
Time spent: 7

## Context
Client scoping: 10-K and 10-Q land outside trading hours, so the intraday-material
set is ownership and insider activity. Real cadence is set with the client; a
15-minute demonstration cadence is a placeholder, not a recommendation.

## Decision
`SEC_FORM_ALLOWLIST` in `src/common/market_models.py` is fixed to Forms 3/4/5 and
amendments, SC 13D/G and amendments, 13F, and the 13H family. Anything else is
**dropped, not failed** — a 10-K is a correct thing to ignore. `FilingRow`
rejects an off-list form at the boundary, so nothing downstream can widen the set
by accident. Cadence is hardcoded at 15 minutes, regular session, and
`scripts/poll_nvda.py --plan` refuses to start when the schedule cannot stay
under the call cap.

## Alternatives considered
| option | why not |
|---|---|
| Poll every form | most of the volume is periodic reports the desk cannot act on intraday |
| Make the allowlist config | a config value is changed without a decision; a constant with an ADR is not |

## Consequences
**We gain:** a small, defensible form set and a cadence that fails loudly rather
than silently over-spending.
**We lose:** 8-K is excluded, and 8-K Item 2.02 is the one periodic-adjacent form
that genuinely lands intraday. Excluding it is the client's call, and it is the
most likely thing this ADR gets revised for. Two further facts worth naming:
Form 4 is due by 10pm ET on the second business day, so most insider filings also
arrive after hours; and **Form 13H is not publicly disseminated** — large-trader
information is confidential under Exchange Act 13(h)(7) — so the allowlist entry
will never match a real filing. The forms stay because the client named them, and
`SEC_FORMS_NOT_PUBLIC` records why they will not appear.
**We revisit when:** the client sets the real cadence, or asks for 8-K.

## Evidence
`tests/test_market_models.py::test_the_allowlist_is_the_intraday_material_set`,
`::test_13h_is_allowlisted_but_flagged_as_never_public`,
`tests/test_poll_nvda.py::test_forms_off_the_allowlist_are_dropped_not_failed`.
