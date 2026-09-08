# ADR-0010: Yahoo's chart endpoint is HARDCODED as the price source for the prototype

Status: accepted — **HARDCODED, pending client decision**
Date: 2026-09-08
Decider: Andrew Nelson
Time spent: 6

## Context
The entitled feed is patched in after the prototype. Building a vendor
abstraction now would be designing against a source whose fields, auth, and
delay we have not seen. Speculative indirection is the more expensive mistake.

## Decision
One source, named in `src/common/market_models.py`: `PRICE_SOURCE`,
`PRICE_SOURCE_URL`, `PRICE_SOURCE_PARAMS`, `PRICE_SOURCE_DELAY_SECONDS`,
`PRICE_SOURCE_UNAVAILABLE`. Every price crosses a pydantic `QuoteSnapshot` before
any model sees it — a malformed payload raises, and raising becomes a FAILED run
with a row in `ops.failure_log`. On HTTP 403 or 429 the poller emits
`FALLBACK_REQUIRED` with a search query; the orchestrator runs Exa and the result
is a `WebPriceObservation` (source tier 6, `writes_to_quote_table: False`), never
a `QuoteSnapshot`. Candidates disagreeing by more than 0.50% return INDETERMINATE.

## Alternatives considered
| option | why not |
|---|---|
| Vendor abstraction layer now | designing an interface against an unseen feed |
| Treat an Exa web price as a quote | one live search returned $226.04, $217.44 and $212.17 for NVDA, three as-ofs, none a venue quote |
| Average the web candidates | manufactures a number no publisher stated |

## Consequences
**We gain:** one code path, validated at the boundary, and a fallback that
degrades to "I cannot source this" instead of to a plausible number.
**We lose:** swapping the source touches `market_models.py` rather than a config
value, and the constants are duplicated in `poll_nvda.py`'s docstring where they
can go stale. The source also carries no bid/ask, so the desk's headline feature
does not work until the entitled feed lands.
**We revisit when:** the client's entitled feed is available. That is the trigger,
not a date.

## Evidence
`tests/test_market_models.py` (17 cases), `tests/test_poll_nvda.py::
test_a_403_asks_for_the_exa_fallback_rather_than_failing_silently`, golden case
`NVDA-002`.
