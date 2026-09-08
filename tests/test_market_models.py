"""Schema validation at the boundary. Every rejection here is a FAILED run
rather than a plausible dict a model would go on to narrate."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.common.market_models import (SEC_FORM_ALLOWLIST, SEC_FORMS_NOT_PUBLIC,
                                      FilingRow, QuoteSnapshot,
                                      WebPriceCandidate, WebPriceObservation,
                                      is_rule612_increment)

NOW = datetime(2026, 9, 8, 17, 45, tzinfo=timezone.utc)


def _quote(**kw):
    base = dict(figi="BBG000BBJQV0", ticker="NVDA", last=Decimal("226.04"),
                prev_close=Decimal("230.36"), currency_code="USD",
                source="yahoo_chart_v8", delay_seconds=900,
                as_of_at_utc=NOW - timedelta(seconds=900), retrieved_at_utc=NOW,
                session="regular", price_basis="adjusted")
    return QuoteSnapshot(**{**base, **kw})


# --- Rule 612 ----------------------------------------------------------------
@pytest.mark.parametrize("px,ok", [
    ("226.04", True), ("226.045", False),        # >= $1.00 -> penny
    ("0.1234", True), ("0.12345", False),        # <  $1.00 -> $0.0001
    ("0", False), ("-1.00", False),
])
def test_rule612_increments(px, ok):
    assert is_rule612_increment(Decimal(px)) is ok


def test_a_subpenny_bid_is_rejected_at_the_boundary():
    with pytest.raises(ValidationError):
        _quote(bid=Decimal("226.0450"), ask=Decimal("226.05"))


# --- provenance --------------------------------------------------------------
def test_a_naive_timestamp_is_rejected():
    with pytest.raises(ValidationError):
        _quote(as_of_at_utc=datetime(2026, 9, 8, 17, 30))


def test_a_quote_from_the_future_is_rejected():
    with pytest.raises(ValidationError):
        _quote(as_of_at_utc=NOW + timedelta(seconds=1))


def test_a_payload_with_no_price_is_rejected():
    with pytest.raises(ValidationError):
        _quote(last=None, bid=None, ask=None)


def test_spread_and_crossed_are_none_without_a_book():
    q = _quote()
    assert q.spread_bps is None and q.is_crossed is None
    assert q.staleness_seconds == 900


def test_spread_is_none_on_a_crossed_book():
    q = _quote(bid=Decimal("12.05"), ask=Decimal("12.01"))
    assert q.is_crossed is True
    assert q.spread_bps is None, "a crossed book has no meaningful mid"


def test_money_serializes_as_a_string():
    row = _quote().model_dump(mode="json")
    assert row["last"] == "226.040000" and isinstance(row["last"], str)


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        _quote(made_up_field="x")


# --- EDGAR -------------------------------------------------------------------
def _filing(**kw):
    base = dict(accession_no="0001045810-26-000110", cik="0001045810", form_type="4",
                filed_at_utc=NOW, primary_doc_url="https://example/f.htm")
    return FilingRow(**{**base, **kw})


def test_a_form_outside_the_hardcoded_allowlist_is_rejected():
    with pytest.raises(ValidationError):
        _filing(form_type="10-K")


def test_the_allowlist_is_the_intraday_material_set():
    for f in ("3", "4", "5", "SC 13D", "SC 13G", "13F-HR", "13H"):
        assert f in SEC_FORM_ALLOWLIST
    for f in ("10-K", "10-Q", "8-K", "S-1"):
        assert f not in SEC_FORM_ALLOWLIST


def test_13h_is_allowlisted_but_flagged_as_never_public():
    """Form 13H is filed through EDGAR but large-trader information is
    confidential under Exchange Act 13(h)(7). The poller will never see one."""
    assert SEC_FORMS_NOT_PUBLIC <= SEC_FORM_ALLOWLIST
    assert "13H" in SEC_FORMS_NOT_PUBLIC


def test_a_malformed_accession_number_is_rejected():
    with pytest.raises(ValidationError):
        _filing(accession_no="1045810-26-110")


# --- the 403 fallback --------------------------------------------------------
def test_disagreeing_web_prices_return_indeterminate():
    """The live Exa search that motivated this returned $226.04 (Sep 8),
    $217.44 (Sep 1, delayed 20 min) and $212.17 (Aug 25) for one symbol."""
    o = WebPriceObservation(
        ticker="NVDA", figi="BBG000BBJQV0", retrieved_at_utc=NOW, query="q",
        candidates=(
            WebPriceCandidate(publisher="a", url="u1", price=Decimal("226.04"), as_of_text="Sep 8"),
            WebPriceCandidate(publisher="b", url="u2", price=Decimal("217.44"), as_of_text="Sep 1"),
            WebPriceCandidate(publisher="c", url="u3", price=Decimal("212.17"), as_of_text="Aug 25")))
    assert o.spread_of_candidates_pct > Decimal("6")
    assert o.verdict == "INDETERMINATE"


def test_a_lone_web_price_is_never_corroborated():
    o = WebPriceObservation(ticker="NVDA", figi="BBG000BBJQV0", retrieved_at_utc=NOW, query="q",
                            candidates=(WebPriceCandidate(publisher="a", url="u", price=Decimal("226.04"),
                                                          as_of_text="Sep 8"),))
    assert o.verdict == "SINGLE_UNCORROBORATED"


def test_a_web_observation_can_never_claim_to_be_a_quote():
    o = WebPriceObservation(ticker="NVDA", figi="BBG000BBJQV0", retrieved_at_utc=NOW,
                            query="q", candidates=())
    assert o.writes_to_quote_table is False and o.source_tier == 6
    with pytest.raises(ValidationError):
        WebPriceCandidate(publisher="a", url="u", price=Decimal("1.00"),
                          as_of_text="now", is_quote=True)
