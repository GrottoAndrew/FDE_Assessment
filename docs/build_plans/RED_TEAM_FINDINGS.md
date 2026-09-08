# Red team pass — 2026-09-08

Scope: `src/common/*.py`, `scripts/poll_nvda.py`, the SQL migrations, `Makefile`,
`frontend/advisor_desk.html`. Method: adversarial read, then execution against
realistic payloads rather than the hand-written fixtures.

All thirteen findings below are defects in code we wrote. **Excluded by design**
as boundary conditions of the prototype, not errors: blocked egress (403 from
`sec.gov` and `finance.yahoo.com`), the stub eval adapter, the absent entitled
feed, the absent agent runtime, and the deliberately empty `wsp.rule` table.

Every finding has a regression test that fails against the prior code. Suite went
138 → 146.

| id | severity | file | defect |
|---|---|---|---|
| RT-01 | **critical** | `market_models.py` | `Money = Annotated[Decimal, Field(decimal_places=6)]` — `decimal_places` is a **maximum** in pydantic. Yahoo serializes prices as IEEE-754 doubles, so `226.03999328613281` raised `decimal_max_places` and **every real payload** returned `FAILED_NO_DATA`. Fixed: `to_money()` coerces onto `numeric(20,6)` with `ROUND_HALF_EVEN` at the boundary, before the Rule 612 check. |
| RT-02 | **critical** | `market_clock.py` | The calendar was bounded only above (`CALENDAR_VERIFIED_THROUGH`). Any earlier date scored against the 2026 holiday table: `2025-12-25` and `2024-07-04` both returned `Session.REGULAR`. Fixed: `CALENDAR_VERIFIED_FROM`, both ends. |
| RT-03 | high | `poll_nvda.py` | `UrllibFetcher.get` caught only `HTTPError`. A DNS failure, reset connection or 30s timeout raised `URLError` out of the EDGAR leg, killed the price leg, and skipped `save_state()` — losing the ETag and the call counters. Fixed: transport failure is `status=0`, a failed call. |
| RT-04 | high | `poll_nvda.py` | `json.loads(r.body)` on the EDGAR 200 path was unguarded; an HTML error page with a 200 crashed the cycle. |
| RT-05 | high | `pull_guard.py` | `_try()` discarded the exception, so a schema bug and a vendor outage wrote byte-identical rows to `ops.failure_log`. Fixed: `evidence["errors"]` carries both attempts' reasons. |
| RT-06 | medium | `pull_guard.py` | The recovery path reused the `attempts == 2` branch and wrote `"verified by a second read"` into the audit record. Nothing was verified — the first read failed and the second had nothing to compare against. |
| RT-07 | high | `poll_nvda.py` | `Decision.SERVE_CACHE` returned `{"status":"cache"}` and **no row**. The dedupe that justifies the entire call budget delivered nothing to the caller. Fixed: the cached row is served with its venue timestamp and cache age. |
| RT-08 | low | `poll_nvda.py` / `quote_budget.py` | `poll_once` writes `b._cache`, `b._calls` and `b._calls_by_day` directly; `QuoteBudget.record_fetch()` and `.cached()` were dead in production. `.cached()` is now used; `record_fetch()` remains test-only because the call is charged separately (documented at the call site). |
| RT-09 | medium | docstring / `Makefile` | The documented cron and `make poll` both used a 15-minute interval — 567 calls/month against a 500 cap, which `--once` **refuses to start on**. Both targets were dead. Fixed to 20 min (420/month, 80 headroom). |
| RT-10 | medium | `poll_nvda.py` | `retrieved_at` was stamped at the top of the cycle. A 30-second EDGAR call made a genuinely fresh print fail `QuoteSnapshot`'s "a quote from the future" check. Fixed: stamp the fetch. |
| RT-11 | high | `poll_nvda.py` | `main()` compared `status == "FAILED"` exactly, so `FAILED_NO_DATA`, `INDETERMINATE_HALTED`, `INDETERMINATE_DISAGREEMENT` and `FALLBACK_REQUIRED` all exited **0**. Cron recorded a clean run over a desk that had served nothing. Fixed: an explicit green set. |
| RT-12 | high | `Makefile` | `make setup` installed `jsonschema` (imported nowhere) and **not** `pydantic` (imported by every module in `src/common/`). A clean checkout died on `ImportError` before the first assertion. Fixed: pinned `requirements.txt`. |
| RT-13 | high | `advisor_desk.html` | Thirteen S&P 500 tickers are also ordinary English words. The ticker-first resolver read "Why is **it** down today?" as Gartner (IT) and "what is that worth right **now**?" as ServiceNow (NOW) — a confident, sourced, fully-cited answer **about the wrong company**. Found by a headless run, not by reading. Fixed: a lowercase homograph is only a ticker when typed as one (`IT`, `$it`), never as a bare word. |

## Orphaned dependencies and dead code

| item | status |
|---|---|
| `jsonschema` | installed, imported nowhere → removed from setup |
| `pydantic` | imported everywhere, installed nowhere → pinned in `requirements.txt` |
| `PRICE_SOURCE_URL` | defined in `market_models`, never used; `poll_nvda` duplicated the literal → now the single definition |
| `scripts/gen_synthetic.py` | referenced by `make seed`, **does not exist** → target aliased to `seed-nvda` |
| `QuoteBudget.cached()` | never called → now used by the SERVE_CACHE path |
| `notify.OPS_ALERT_EMAIL` | defined, never used. **Left in place**: it is the address the stale-data path will need, and deleting it would hide the gap rather than close it. |
| `urllib.error` | used but never imported (it resolved only because `urllib.request` imports it internally) → now imported explicitly |

## Known and accepted, not fixed

* **`QuoteBudget` cache freshness is measured from `retrieved_epoch`, not `as_of_epoch`.**
  A cached row whose venue timestamp is hours old is still a cache hit. Not changed,
  because the row carries `as_of_at_utc` and `staleness_seconds` and both the API and
  the desk display them — the age is disclosed, never implied. Making it a hard refusal
  is a **client threshold decision**, not ours.
* **`_calls_by_day` grows without bound** in `.poll_state.json`. ~40 bytes/day. Prune at
  month rollover when the state file gets an owner.
* **Budget periods are UTC, the market day is ET.** No practical divergence, because
  fetches only happen in the regular session and the UTC and ET dates always agree
  inside 09:30–16:00 ET. Documented so it is not rediscovered.
* **`normalize_chart` takes `session` from Yahoo's `marketState`**, which can contradict
  the NYSE clock that already gated the call. Left as-is: two sources disagreeing is
  information, and overwriting one with the other would destroy it.

## Method note

Twelve of these thirteen survived a green 138-test suite. They survived because the
fixtures were hand-written with clean values and egress is blocked, so **no real payload
ever crossed a boundary**. A green suite proves the code does what the tests say; it
does not prove the tests describe the source. The cheapest control against this class
is a recorded real payload per source, checked in — which is what `--record` exists for
and what blocked egress has so far prevented.
