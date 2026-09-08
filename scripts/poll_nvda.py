#!/usr/bin/env python3
"""
poll_nvda.py — one poll cycle for NVDA: EDGAR filings + delayed price.

    python3 scripts/poll_nvda.py --plan            # budget arithmetic, no network
    python3 scripts/poll_nvda.py --once            # one cycle
    python3 scripts/poll_nvda.py --once --record   # also freeze fixtures for the golden set

Cron (the durable form — a session dies, a crontab does not). Every 15 minutes,
regular session only, Mon-Fri, in the box's local time:

    */15 13-20 * * 1-5  cd /path/to/FDE_Assessment && .venv/bin/python scripts/poll_nvda.py --once >> logs/poll.log 2>&1

TWO SOURCES, TWO BUDGETS, because they fail differently:

  EDGAR   https://data.sec.gov/submissions/CIK0001045810.json
          Rate-limited, not call-capped. A declared User-Agent is required by
          the SEC fair-access policy. Conditional GET (ETag / If-Modified-Since)
          makes an unchanged poll a 304 costing no quota and no parsing — one
          issuer's filings change a few times a month, so nearly every poll is
          a 304 by design.

  PRICE   https://query1.finance.yahoo.com/v8/finance/chart/NVDA
          Hard monthly cap. Every call goes through QuoteBudget.

The two browser URLs in the brief (sec.gov/edgar/browse and finance.yahoo.com/chart)
are JavaScript shells: fetching them returns an empty app frame, not data. The
endpoints above are what those pages call. The chart URL's base64 blob decodes to
1-minute bars, regular session only, split/dividend adjusted, America/New_York —
which is what CHART_PARAMS below reproduces.

WHAT THIS SOURCE CANNOT GIVE YOU: the chart endpoint carries no bid, no ask, and
therefore no spread. It returns last, previous close, and OHLCV. The desk's
headline feature is bid/ask/spread, so this is a real capability gap, not a
formatting one. bid and ask are recorded as null and listed in
`unavailable_fields`; quote_snapshot_agent returns INDETERMINATE for a bid/ask
request rather than deriving a spread from OHLC, which would be a fabricated
number wearing a real timestamp.
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.common.market_models import (PRICE_SOURCE, PRICE_SOURCE_DELAY_SECONDS,  # noqa: E402
                                      PRICE_SOURCE_PARAMS, PRICE_SOURCE_UNAVAILABLE,
                                      SEC_FORM_ALLOWLIST, FilingRow, QuoteSnapshot)
from src.common.quote_budget import CachedQuote, Decision, QuoteBudget  # noqa: E402

CIK = "0001045810"          # NVIDIA Corp
TICKER = "NVDA"
FIGI = "BBG000BBJQV0"       # NVDA common; resolve through md.security, never by ticker

EDGAR_URL = f"https://data.sec.gov/submissions/CIK{CIK}.json"
CHART_URL = f"https://query1.finance.yahoo.com/v8/finance/chart/{TICKER}"
CHART_PARAMS = PRICE_SOURCE_PARAMS   # HARDCODED in market_models (ADR-0010)

STATE_PATH = ROOT / "eval_output" / ".poll_state.json"
FIXTURE_DIR = ROOT / "eval_workflows" / "fixtures" / "nvda"

# US equity market, regular session, in minutes past midnight ET.
RTH_OPEN_MIN, RTH_CLOSE_MIN = 9 * 60 + 30, 16 * 60
TRADING_DAYS_PER_MONTH = 21


# ---------------------------------------------------------------------------
# Budget arithmetic — run this BEFORE scheduling anything.
# ---------------------------------------------------------------------------
@dataclass
class PollPlan:
    interval_minutes: int
    monthly_cap: int
    session: str = "regular"
    trading_days: int = TRADING_DAYS_PER_MONTH

    @property
    def polls_per_day(self) -> int:
        span = RTH_CLOSE_MIN - RTH_OPEN_MIN if self.session == "regular" else 24 * 60
        return span // self.interval_minutes + (1 if self.session == "regular" else 0)

    @property
    def polls_per_month(self) -> int:
        return self.polls_per_day * self.trading_days

    @property
    def fits(self) -> bool:
        return self.polls_per_month <= self.monthly_cap

    @property
    def max_interval_that_fits(self) -> int:
        """Smallest 5-minute-aligned interval whose schedule fits the cap."""
        for iv in range(5, 121, 5):
            if PollPlan(iv, self.monthly_cap, self.session, self.trading_days).fits:
                return iv
        return 0

    def report(self) -> str:
        lines = [
            f"symbol                {TICKER}  ({FIGI})",
            f"interval              every {self.interval_minutes} min, {self.session} session",
            f"polls/day             {self.polls_per_day}",
            f"trading days/month    {self.trading_days}",
            f"polls/month           {self.polls_per_month}",
            f"monthly cap           {self.monthly_cap}",
        ]
        if self.fits:
            head = self.monthly_cap - self.polls_per_month
            lines.append(f"VERDICT               FITS — {head} calls of headroom for ad-hoc advisor requests")
            if head < self.polls_per_month * 0.2:
                lines.append("                      headroom under 20%: an advisor asking on demand will exhaust it")
        else:
            over = self.polls_per_month - self.monthly_cap
            lines += [
                f"VERDICT               DOES NOT FIT — {over} calls over, before a single advisor request",
                f"                      fixes: raise the cap to >= {self.polls_per_month + 100},",
                f"                      or poll every {self.max_interval_that_fits} min instead of {self.interval_minutes}",
            ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Fetching — injectable so the logic is testable with no network.
# ---------------------------------------------------------------------------
@dataclass
class Response:
    status: int
    body: bytes = b""
    headers: dict = field(default_factory=dict)


class UrllibFetcher:
    def __init__(self, user_agent: str):
        self.user_agent = user_agent
        bundle = "/root/.ccr/ca-bundle.crt"
        self.ctx = ssl.create_default_context(cafile=bundle) if os.path.exists(bundle) else None

    def get(self, url: str, headers: dict | None = None) -> Response:
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent, **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=30, context=self.ctx) as r:
                return Response(r.status, r.read(), dict(r.headers))
        except urllib.error.HTTPError as e:
            return Response(e.code, e.read() if e.fp else b"", dict(e.headers or {}))


# ---------------------------------------------------------------------------
# Normalization — into the shapes 004_domain.sql already holds.
# ---------------------------------------------------------------------------
def normalize_chart(payload: dict, delay_seconds: int, retrieved_at: datetime) -> QuoteSnapshot:
    """Yahoo chart -> a validated QuoteSnapshot.

    Every failure here is an exception, and an exception is a FAILED run with a
    row in ops.failure_log. Nothing half-parsed reaches a model.
    """
    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        raise ValueError("chart payload carries no result: treat as a failed call, not an empty quote")
    meta = result[0]["meta"]

    def money(v):
        return None if v is None else Decimal(str(v))

    mt = meta.get("regularMarketTime")
    if not mt:
        raise ValueError("no regularMarketTime: a price without a venue timestamp is not a quote")
    state = (meta.get("marketState") or "").upper()
    session = {"REGULAR": "regular", "PRE": "pre", "POST": "post",
               "POSTPOST": "closed", "CLOSED": "closed", "PREPRE": "closed"}.get(state, "closed")
    return QuoteSnapshot(
        figi=FIGI, ticker=meta.get("symbol", TICKER),
        last=money(meta.get("regularMarketPrice")),
        prev_close=money(meta.get("chartPreviousClose") or meta.get("previousClose")),
        currency_code=meta.get("currency", "USD"),
        source=PRICE_SOURCE,
        delay_seconds=delay_seconds,
        as_of_at_utc=datetime.fromtimestamp(mt, timezone.utc),
        retrieved_at_utc=retrieved_at,
        session=session,
        is_halted=None,             # this source does not report halt status
        price_basis="adjusted",     # the chart layout requests split/dividend adjusted
        unavailable_fields=PRICE_SOURCE_UNAVAILABLE,
    )


def normalize_submissions(payload: dict, since_accession: str | None) -> list[FilingRow]:
    """EDGAR submissions -> validated FilingRows, newest first, stopping at the
    last one already seen.

    Forms outside SEC_FORM_ALLOWLIST are dropped silently and by design: the
    client scoped this to ownership and insider activity because periodic reports
    land outside trading hours (ADR-0011). Dropping is not the same as failing —
    a 10-K is a correct thing to ignore, not an error.
    """
    recent = ((payload.get("filings") or {}).get("recent")) or {}
    if not recent.get("accessionNumber"):
        return []
    rows: list[FilingRow] = []
    for i in range(len(recent["accessionNumber"])):
        acc = recent["accessionNumber"][i]
        if since_accession and acc == since_accession:
            break
        get = lambda c: (recent.get(c) or [None] * (i + 1))[i]  # noqa: E731
        form = get("form")
        if form not in SEC_FORM_ALLOWLIST:
            continue
        filed = get("acceptanceDateTime") or get("filingDate")
        rows.append(FilingRow(
            accession_no=acc,
            cik=CIK,
            form_type=form,
            filed_at_utc=_parse_edgar_ts(filed),
            period_of_report=get("reportDate") or None,
            primary_doc_url=f"https://www.sec.gov/Archives/edgar/data/{int(CIK)}/"
                            f"{acc.replace('-', '')}/{get('primaryDocument')}",
        ))
    return rows


def _parse_edgar_ts(v: str) -> datetime:
    """EDGAR gives either an acceptance datetime or a bare filing date. A bare
    date is midnight UTC and is labeled as such rather than guessed into a time."""
    if v.endswith("Z"):
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    if "T" in v:
        return datetime.fromisoformat(v).replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(v + "T00:00:00").replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# State — the poller is a cron job, so its memory has to live on disk.
# ---------------------------------------------------------------------------
def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"edgar_etag": None, "edgar_last_modified": None, "last_accession": None,
            "quote_calls": {}, "quote_calls_by_day": {}, "quote_cache": {}}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))


def budget_from_state(state: dict, cap: int, pacing: bool) -> QuoteBudget:
    """Rehydrate counters AND the cache.

    A cron-invoked poller is a new process on every tick, so an in-process cache
    is no cache at all: the TTL never fires, the dedupe never fires, and every
    tick spends a call it did not have to. The cache has to outlive the process
    or the whole budget design is decorative.
    """
    b = QuoteBudget(monthly_limit=cap, source="yahoo", enforce_daily_pacing=pacing)
    b._calls = {tuple(map(int, k.split("-"))): v for k, v in state.get("quote_calls", {}).items()}
    b._calls_by_day = {tuple(map(int, k.split("-"))): v for k, v in state.get("quote_calls_by_day", {}).items()}
    for figi, c in (state.get("quote_cache") or {}).items():
        b._cache[figi] = CachedQuote(figi=figi, payload=c["payload"], as_of_epoch=c["as_of_epoch"],
                                     retrieved_epoch=c["retrieved_epoch"], source=c["source"],
                                     delay_seconds=c["delay_seconds"], session=c["session"])
    return b


def budget_to_state(b: QuoteBudget, state: dict) -> None:
    state["quote_calls"] = {"-".join(map(str, k)): v for k, v in b._calls.items()}
    state["quote_calls_by_day"] = {"-".join(map(str, k)): v for k, v in b._calls_by_day.items()}
    state["quote_cache"] = {
        figi: {"payload": c.payload, "as_of_epoch": c.as_of_epoch,
               "retrieved_epoch": c.retrieved_epoch, "source": c.source,
               "delay_seconds": c.delay_seconds, "session": c.session}
        for figi, c in b._cache.items()
    }


# ---------------------------------------------------------------------------
# One cycle
# ---------------------------------------------------------------------------
def poll_once(fetcher, state: dict, cap: int, delay_seconds: int, pacing: bool,
              now: datetime | None = None, record: bool = False) -> dict:
    now = now or datetime.now(timezone.utc)
    out = {"ts": now.isoformat().replace("+00:00", "Z"), "edgar": None, "quote": None}

    # --- EDGAR: conditional GET. A 304 is the expected outcome, not a miss. ---
    headers = {"Accept": "application/json"}
    if state.get("edgar_etag"):
        headers["If-None-Match"] = state["edgar_etag"]
    elif state.get("edgar_last_modified"):
        headers["If-Modified-Since"] = state["edgar_last_modified"]
    r = fetcher.get(EDGAR_URL, headers)
    if r.status == 304:
        out["edgar"] = {"status": "not_modified", "new_filings": 0}
    elif r.status == 200:
        payload = json.loads(r.body)
        rows = normalize_submissions(payload, state.get("last_accession"))
        if rows:
            state["last_accession"] = rows[0].accession_no
        state["edgar_etag"] = r.headers.get("ETag")
        state["edgar_last_modified"] = r.headers.get("Last-Modified")
        dumped = [r_.model_dump(mode="json") for r_ in rows]
        out["edgar"] = {"status": "ok", "new_filings": len(rows), "filings": dumped[:10]}
        if record and rows:
            _freeze("filings", dumped, now)
    else:
        # Never a default. A failed call is FAILED, and the caller writes ops.failure_log.
        out["edgar"] = {"status": "FAILED", "http_status": r.status}

    # --- PRICE: budget first, fetch second. ---------------------------------
    b = budget_from_state(state, cap, pacing)
    session = _session_for(now)
    decision = b.decide(FIGI, session, now=now.timestamp())
    if decision is Decision.SERVE_CACHE:
        out["quote"] = {"status": "cache", "spent": 0}
    elif decision is Decision.BUDGET_EXHAUSTED:
        out["quote"] = {"status": "FAILED", "reason": "budget_exhausted",
                        "calls_used": b.calls_used(now.timestamp()), "cap": cap}
    else:
        r = fetcher.get(f"{CHART_URL}?{CHART_PARAMS}", {"Accept": "application/json"})
        if r.status == 200:
            try:
                row = normalize_chart(json.loads(r.body), delay_seconds, now)
            except ValueError as e:
                b.record_spent_call(now=now.timestamp())      # it reached the source; it counts
                budget_to_state(b, state)
                out["quote"] = {"status": "FAILED", "reason": str(e)}
                return out
            payload = row.model_dump(mode="json")
            b.record_fetch(CachedQuote(figi=FIGI, payload=payload,
                                       as_of_epoch=now.timestamp() - delay_seconds,
                                       retrieved_epoch=now.timestamp(), source="yahoo",
                                       delay_seconds=delay_seconds, session=session),
                           now=now.timestamp())
            out["quote"] = {"status": "ok", "spent": 1, "row": payload,
                            "remaining": b.remaining(now.timestamp())}
            if record:
                _freeze("quote", payload, now)
        elif r.status in (403, 429):
            # Blocked or throttled by the source. The fallback is NOT a library
            # call: Exa is an agent tool, so the poller emits the exact query and
            # the orchestrator runs it. Whatever comes back is a
            # WebPriceObservation, never a QuoteSnapshot — see ADR-0010.
            b.record_spent_call(now=now.timestamp())
            out["quote"] = {
                "status": "FALLBACK_REQUIRED",
                "http_status": r.status,
                "fallback": "exa_web_search",
                "query": f"{TICKER} stock quote page showing current price, previous close, bid and ask",
                "contract": "returns WebPriceObservation (source_tier 6, writes_to_quote_table false); "
                            "candidates disagreeing by more than 0.50% return INDETERMINATE",
            }
        else:
            b.record_spent_call(now=now.timestamp())
            out["quote"] = {"status": "FAILED", "http_status": r.status}
    budget_to_state(b, state)
    return out


def _session_for(now: datetime) -> str:
    """UTC -> ET without a tz database dependency: ET is UTC-4 in DST, UTC-5 otherwise.
    Wrong by an hour for three weeks a year, which shortens a TTL rather than
    lengthening one. Replace with zoneinfo before this touches real money."""
    et_min = ((now.hour - 4) % 24) * 60 + now.minute
    if now.weekday() >= 5:
        return "closed"
    if RTH_OPEN_MIN <= et_min < RTH_CLOSE_MIN:
        return "regular"
    if 4 * 60 <= et_min < RTH_OPEN_MIN:
        return "pre"
    if RTH_CLOSE_MIN <= et_min < 20 * 60:
        return "post"
    return "closed"


def _freeze(kind: str, data, now: datetime) -> None:
    """Golden-set fixtures. A market-data eval that hits a live feed fails at
    09:30 for reasons unrelated to the code (gap G-15)."""
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    p = FIXTURE_DIR / f"{kind}_{now.strftime('%Y%m%dT%H%M%SZ')}.json"
    p.write_text(json.dumps(data, indent=2))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true", help="budget arithmetic only, no network")
    ap.add_argument("--once", action="store_true", help="run one poll cycle")
    ap.add_argument("--record", action="store_true", help="freeze results as golden fixtures")
    ap.add_argument("--interval", type=int, default=15)
    ap.add_argument("--cap", type=int, default=int(os.environ.get("QUOTE_MONTHLY_CALL_LIMIT", 500)))
    a = ap.parse_args()

    plan = PollPlan(a.interval, a.cap)
    if a.plan or not a.once:
        print(plan.report())
        return 0 if plan.fits else 2

    if not plan.fits:
        print(plan.report(), file=sys.stderr)
        print("\nrefusing to start: this schedule cannot stay under the cap.", file=sys.stderr)
        return 2

    ua = os.environ.get("EDGAR_USER_AGENT")
    if not ua:
        print("EDGAR_USER_AGENT is unset. The SEC fair-access policy requires a "
              "declared identity on every request; running without one risks the "
              "firm's IP.", file=sys.stderr)
        return 2

    state = load_state()
    result = poll_once(UrllibFetcher(ua), state,
                       cap=a.cap,
                       delay_seconds=int(os.environ.get("QUOTE_DELAY_SECONDS", 900)),
                       pacing=os.environ.get("QUOTE_ENFORCE_DAILY_PACING", "true") == "true",
                       record=a.record)
    save_state(state)
    print(json.dumps(result, indent=2))
    failed = [k for k in ("edgar", "quote") if (result.get(k) or {}).get("status") == "FAILED"]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
