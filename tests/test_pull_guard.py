"""The gate sequence: clock, fetch, second check, compare, halt."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.common.market_clock import reading
from src.common.market_models import QuoteSnapshot
from src.common.notify import CCO_ALERT_EMAIL, RecordingTransport
from src.common.pull_guard import (HaltStatus, Outcome, guarded_pull)

OPEN = datetime.fromisoformat("2026-09-08T17:45:00+00:00")     # 13:45 ET, Tuesday
CLOSED = datetime.fromisoformat("2026-09-08T23:45:00+00:00")   # 19:45 ET
HOLIDAY = datetime.fromisoformat("2026-09-07T17:45:00+00:00")  # Labor Day
FIGI, TICKER = "BBG000BBJQV0", "NVDA"


def _q(last="226.04", at=OPEN):
    return QuoteSnapshot(figi=FIGI, ticker=TICKER, last=Decimal(last),
                         prev_close=Decimal("230.36"), currency_code="USD",
                         source="yahoo_chart_v8", delay_seconds=900,
                         as_of_at_utc=at - timedelta(seconds=900), retrieved_at_utc=at,
                         session="regular", price_basis="adjusted")


class Seq:
    """Returns queued results in order; None means an empty read, an Exception
    class means the payload failed validation."""
    def __init__(self, *items):
        self.items, self.calls = list(items), 0

    def __call__(self):
        self.calls += 1
        item = self.items.pop(0) if self.items else None
        if isinstance(item, type) and issubclass(item, Exception):
            raise item("schema validation failed")
        return item


class FixedHalt:
    def __init__(self, s): self.s = s
    def status(self, figi): return self.s


# --- 1. clock ----------------------------------------------------------------
def test_a_closed_market_spends_nothing():
    f = Seq(_q())
    r = guarded_pull(f, FIGI, TICKER, now=CLOSED)
    assert r.outcome is Outcome.SKIPPED_MARKET_CLOSED
    assert r.calls_spent == 0 and f.calls == 0, "the cheapest call is the one not made"


def test_a_holiday_spends_nothing():
    f = Seq(_q())
    r = guarded_pull(f, FIGI, TICKER, now=HOLIDAY)
    assert r.outcome is Outcome.SKIPPED_MARKET_CLOSED
    assert "holiday" in r.reason and f.calls == 0


# --- 2/3. second check -------------------------------------------------------
def test_a_good_read_is_verified_by_a_second_read():
    f = Seq(_q("226.04"), _q("226.04"))
    r = guarded_pull(f, FIGI, TICKER, now=OPEN)
    assert r.outcome is Outcome.OK and r.attempts == 2
    assert r.quote.last == Decimal("226.04")


def test_an_empty_read_gets_exactly_one_recheck():
    f = Seq(None, _q("226.04"))
    r = guarded_pull(f, FIGI, TICKER, now=OPEN)
    assert r.outcome is Outcome.OK
    assert r.evidence["recovered_on_second_check"] is True
    assert f.calls == 2, "one re-check, not a loop"


def test_two_empty_reads_fail_loudly_with_a_triage_class():
    f = Seq(None, None)
    r = guarded_pull(f, FIGI, TICKER, now=OPEN)
    assert r.outcome is Outcome.FAILED_NO_DATA
    assert r.triage_class == "source_unavailable" and r.quote is None


def test_a_payload_that_fails_validation_counts_as_no_data():
    f = Seq(ValueError, ValueError)
    r = guarded_pull(f, FIGI, TICKER, now=OPEN)
    assert r.outcome is Outcome.FAILED_NO_DATA, "half-parsed is not partial, it is nothing"


# --- 4. compare --------------------------------------------------------------
def test_two_reads_that_disagree_are_indeterminate_not_averaged():
    f = Seq(_q("226.04"), _q("241.00"))
    r = guarded_pull(f, FIGI, TICKER, now=OPEN)
    assert r.outcome is Outcome.INDETERMINATE_DISAGREEMENT
    assert r.quote is None, "neither read may be served; one of them is wrong"
    assert r.triage_class == "source_disagreement"
    assert Decimal(r.evidence["delta_pct"]) > Decimal("6")


def test_movement_inside_tolerance_is_accepted():
    f = Seq(_q("226.04"), _q("226.50"))     # 0.20%
    assert guarded_pull(f, FIGI, TICKER, now=OPEN).outcome is Outcome.OK


def test_a_verification_read_that_vanishes_is_indeterminate():
    f = Seq(_q("226.04"), None)
    r = guarded_pull(f, FIGI, TICKER, now=OPEN)
    assert r.outcome is Outcome.INDETERMINATE_DISAGREEMENT
    assert r.triage_class == "unstable_source"


# --- 5. halt -----------------------------------------------------------------
def test_a_halted_security_is_indeterminate_and_the_cco_is_emailed():
    t = RecordingTransport()
    f = Seq(_q("226.04"), _q("226.04"))
    r = guarded_pull(f, FIGI, TICKER, now=OPEN,
                     halt_check=FixedHalt(HaltStatus.HALTED), transport=t)
    assert r.outcome is Outcome.INDETERMINATE_HALTED and r.quote is None
    assert len(t.sent) == 1
    n = t.sent[0]
    assert n.to == CCO_ALERT_EMAIL and n.severity == "critical"
    assert n.event_type == "trading_halt" and n.figi == FIGI
    assert TICKER in n.subject
    assert r.evidence["cco_notice_receipt"].startswith("recorded:")


def test_a_trading_security_sends_no_mail():
    t = RecordingTransport()
    f = Seq(_q(), _q())
    r = guarded_pull(f, FIGI, TICKER, now=OPEN,
                     halt_check=FixedHalt(HaltStatus.TRADING), transport=t)
    assert r.outcome is Outcome.OK and r.halt_verified is True
    assert t.sent == []


def test_unknown_halt_status_is_served_but_never_claimed_as_verified():
    """The interim source has no halt field. UNKNOWN is not False, and the desk
    has to say the halt state is unverified rather than imply it checked."""
    f = Seq(_q(), _q())
    r = guarded_pull(f, FIGI, TICKER, now=OPEN)
    assert r.outcome is Outcome.OK
    assert r.halt_verified is False
    assert r.evidence["halt_status"] == "unknown"


# --- the verify flag ---------------------------------------------------------
def test_verification_is_optional_because_it_doubles_the_call_cost():
    """15-minute polling is 567 calls a month; verified, it is 1,134. Scheduled
    polls skip the verification read because the next tick is the check."""
    f = Seq(_q("226.04"), _q("241.00"))
    r = guarded_pull(f, FIGI, TICKER, now=OPEN, verify=False)
    assert r.outcome is Outcome.OK and f.calls == 1
    assert r.evidence["verified"] is False


def test_the_recheck_on_no_data_happens_even_with_verify_off():
    """A re-check on failure costs a call only when something already broke."""
    f = Seq(None, _q("226.04"))
    r = guarded_pull(f, FIGI, TICKER, now=OPEN, verify=False)
    assert r.outcome is Outcome.OK and f.calls == 2


def test_a_failed_pull_keeps_the_reason_it_failed():
    """RT-05. The exception was discarded, so a schema bug and a vendor outage
    produced byte-identical rows in ops.failure_log."""
    def boom():
        raise ValueError("226.03999328613281 has more than 6 decimal places")
    res = guarded_pull(boom, FIGI, TICKER, now=OPEN)
    assert res.outcome is Outcome.FAILED_NO_DATA
    assert len(res.evidence["errors"]) == 2
    assert "decimal places" in res.evidence["errors"][0]


def test_a_recovered_read_is_not_labelled_verified():
    """RT-06. The recovery path reused the attempts==2 branch and wrote
    "verified by a second read" into the audit record. Nothing was verified —
    the first read failed and the second had nothing to compare against."""
    calls = {"n": 0}
    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("empty payload")
        return _q()
    res = guarded_pull(flaky, FIGI, TICKER, now=OPEN)
    assert res.outcome is Outcome.OK
    assert res.attempts == 2
    assert "verified" not in res.reason
    assert res.evidence["recovered_on_second_check"] is True
    assert "empty payload" in res.evidence["first_read_error"]
