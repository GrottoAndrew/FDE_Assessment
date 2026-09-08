"""Poller logic, proven with recorded payloads. No network, no clock drift."""
import json
from datetime import datetime, timezone

import pytest

from scripts.poll_nvda import (CIK, PollPlan, Response, normalize_chart,
                               normalize_submissions, poll_once, _session_for)

NOW = datetime(2026, 9, 8, 17, 45, 0, tzinfo=timezone.utc)   # 13:45 ET, Tuesday, RTH

CHART = {"chart": {"result": [{"meta": {
    "symbol": "NVDA", "currency": "USD", "marketState": "REGULAR",
    "regularMarketPrice": 178.4567, "chartPreviousClose": 176.12,
    "regularMarketTime": int(NOW.timestamp()) - 900, "exchangeName": "NMS"}}], "error": None}}

SUBMISSIONS = {"cik": CIK, "filings": {"recent": {
    "accessionNumber": ["0001045810-26-000110", "0001045810-26-000104"],
    "form": ["8-K", "10-Q"],
    "filingDate": ["2026-09-08", "2026-08-27"],
    "reportDate": ["2026-09-05", "2026-07-27"],
    "primaryDocument": ["nvda-20260905.htm", "nvda-20260727.htm"],
    "acceptanceDateTime": ["2026-09-08T16:31:02.000Z", "2026-08-27T16:05:11.000Z"]}}}


class FakeFetcher:
    """Returns queued responses by URL substring; records what was asked for."""
    def __init__(self, plan):
        self.plan, self.calls = plan, []

    def get(self, url, headers=None):
        self.calls.append((url, headers or {}))
        for key, resp in self.plan.items():
            if key in url:
                return resp
        raise AssertionError(f"unexpected fetch: {url}")


def _state():
    return {"edgar_etag": None, "edgar_last_modified": None, "last_accession": None,
            "quote_calls": {}, "quote_calls_by_day": {}, "quote_cache": {}}


# --- the budget arithmetic, which is the whole point of --plan ---------------
def test_fifteen_minute_polling_does_not_fit_a_500_call_cap():
    p = PollPlan(interval_minutes=15, monthly_cap=500)
    assert p.polls_per_day == 27 and p.polls_per_month == 567
    assert not p.fits, "567 > 500; the schedule must refuse to start rather than fail mid-month"


def test_twenty_minute_polling_fits():
    assert PollPlan(interval_minutes=20, monthly_cap=500).fits


def test_the_planner_names_the_interval_that_would_fit():
    assert PollPlan(interval_minutes=15, monthly_cap=500).max_interval_that_fits == 20


# --- normalization -----------------------------------------------------------
def test_chart_gives_no_bid_or_ask_and_says_so():
    """The desk's headline feature is bid/ask/spread and this source has neither.
    Deriving a spread from OHLC would be a fabricated number with a real timestamp."""
    row = normalize_chart(CHART, delay_seconds=900, retrieved_at=NOW)
    assert row["bid"] is None and row["ask"] is None
    for f in ("bid", "ask", "spread_bps", "mid"):
        assert f in row["unavailable_fields"]


def test_prices_are_strings_at_full_scale():
    row = normalize_chart(CHART, delay_seconds=900, retrieved_at=NOW)
    assert row["last"] == "178.456700", "a JSON float loses the tail, and the tail is where Rule 612 lives"
    assert isinstance(row["prev_close"], str)


def test_every_price_carries_its_provenance():
    row = normalize_chart(CHART, delay_seconds=900, retrieved_at=NOW)
    for k in ("source", "delay_seconds", "as_of_at_utc", "retrieved_at_utc", "currency_code"):
        assert row[k] is not None
    assert row["delay_seconds"] == 900, "never 0 until the entitled feed lands"


def test_an_empty_chart_result_raises_instead_of_returning_an_empty_quote():
    with pytest.raises(ValueError):
        normalize_chart({"chart": {"result": []}}, 900, NOW)


def test_submissions_stop_at_the_last_seen_accession():
    rows = normalize_submissions(SUBMISSIONS, since_accession="0001045810-26-000104")
    assert [r["accession_no"] for r in rows] == ["0001045810-26-000110"]
    assert rows[0]["primary_doc_url"].endswith("/1045810/000104581026000110/nvda-20260905.htm")


def test_session_mapping_uses_eastern_market_hours():
    assert _session_for(NOW) == "regular"
    assert _session_for(NOW.replace(hour=23)) == "post"
    assert _session_for(NOW.replace(day=12)) == "closed"   # 2026-09-12 is a Saturday


# --- one cycle ---------------------------------------------------------------
def test_unchanged_edgar_returns_304_and_costs_nothing():
    f = FakeFetcher({"data.sec.gov": Response(304), "query1": Response(200, json.dumps(CHART).encode())})
    st = _state(); st["edgar_etag"] = 'W/"abc"'
    out = poll_once(f, st, cap=500, delay_seconds=900, pacing=False, now=NOW)
    assert out["edgar"] == {"status": "not_modified", "new_filings": 0}
    assert f.calls[0][1]["If-None-Match"] == 'W/"abc"'


def test_new_filing_is_picked_up_and_remembered():
    f = FakeFetcher({"data.sec.gov": Response(200, json.dumps(SUBMISSIONS).encode(), {"ETag": 'W/"z"'}),
                     "query1": Response(200, json.dumps(CHART).encode())})
    st = _state()
    out = poll_once(f, st, cap=500, delay_seconds=900, pacing=False, now=NOW)
    assert out["edgar"]["new_filings"] == 2
    assert st["last_accession"] == "0001045810-26-000110"
    assert st["edgar_etag"] == 'W/"z"'


def test_the_cache_survives_the_process_because_cron_starts_a_new_one():
    """Regression: the budget's cache lived in memory, so every cron tick began
    with an empty cache and spent a call the TTL should have covered."""
    f = FakeFetcher({"data.sec.gov": Response(304), "query1": Response(200, json.dumps(CHART).encode())})
    st = _state()
    poll_once(f, st, cap=500, delay_seconds=900, pacing=False, now=NOW)
    assert st["quote_cache"], "the cache must be serialized into state"
    assert st["quote_cache"]["BBG000BBJQV0"]["payload"]["last"] == "178.456700"


def test_a_second_poll_inside_the_ttl_spends_no_quote_call():
    f = FakeFetcher({"data.sec.gov": Response(304), "query1": Response(200, json.dumps(CHART).encode())})
    st = _state()
    poll_once(f, st, cap=500, delay_seconds=900, pacing=False, now=NOW)
    assert st["quote_calls"] == {"2026-9": 1}
    out = poll_once(f, st, cap=500, delay_seconds=900, pacing=False, now=NOW)
    assert out["quote"]["status"] == "cache"
    assert st["quote_calls"] == {"2026-9": 1}


def test_exhausted_cap_fails_rather_than_returning_the_cached_row():
    f = FakeFetcher({"data.sec.gov": Response(304), "query1": Response(200, json.dumps(CHART).encode())})
    st = _state()
    poll_once(f, st, cap=1, delay_seconds=900, pacing=False, now=NOW)
    later = NOW.replace(hour=19)          # past the regular-session TTL
    out = poll_once(f, st, cap=1, delay_seconds=900, pacing=False, now=later)
    assert out["quote"]["status"] == "FAILED" and out["quote"]["reason"] == "budget_exhausted"
    assert "row" not in out["quote"], "a cached row must not ride out on an exhausted budget"


def test_a_failed_quote_call_still_counts_against_the_cap():
    f = FakeFetcher({"data.sec.gov": Response(304), "query1": Response(500)})
    st = _state()
    out = poll_once(f, st, cap=500, delay_seconds=900, pacing=False, now=NOW)
    assert out["quote"]["status"] == "FAILED"
    assert st["quote_calls"] == {"2026-9": 1}, "it reached the source; pretending otherwise blows the cap"


def test_edgar_failure_is_reported_not_defaulted():
    f = FakeFetcher({"data.sec.gov": Response(403), "query1": Response(200, json.dumps(CHART).encode())})
    out = poll_once(f, _state(), cap=500, delay_seconds=900, pacing=False, now=NOW)
    assert out["edgar"] == {"status": "FAILED", "http_status": 403}
