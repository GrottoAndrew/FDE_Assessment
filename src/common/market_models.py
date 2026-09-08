"""
market_models.py — pydantic schemas at every boundary where outside data enters.

The point is not tidiness. A model never sees a raw HTML page or an unvalidated
JSON blob; it sees a typed object that already failed loudly if a field was
missing, malformed, or off a lawful price increment. Anything the schema cannot
validate becomes an exception, and an exception becomes a FAILED run with a row
in ops.failure_log — not a plausible-looking dict that a model then narrates.

That is the hallucination control. Not a prompt telling the model to be careful.

HARDCODED FOR THE PROTOTYPE (ADR-0010, ADR-0011):
  * the price source is Yahoo's chart endpoint — one source, no vendor abstraction
  * the SEC form allowlist is fixed to the intraday-material set
Both are pinned pending client decisions. See the ADRs before changing either.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Literal, Optional

from pydantic import (BaseModel, ConfigDict, Field, computed_field,
                      field_serializer, field_validator, model_validator)

# --- HARDCODED: price source ------------------------------------------------
PRICE_SOURCE = "yahoo_chart_v8"
PRICE_SOURCE_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
PRICE_SOURCE_PARAMS = "interval=1m&range=1d&includePrePost=false&events=div%2Csplit"
PRICE_SOURCE_DELAY_SECONDS = 900
# The chart endpoint has no quote book. These are not "missing"; they do not exist
# in this source, and the difference matters when the entitled feed lands.
PRICE_SOURCE_UNAVAILABLE = ("bid", "ask", "bid_size", "ask_size", "spread_bps", "mid", "is_halted")

# --- HARDCODED: SEC form allowlist ------------------------------------------
# Client's scoping: periodic reports (10-K/10-Q) land outside trading hours, so
# the intraday-material set is ownership and insider activity.
SEC_FORM_ALLOWLIST = frozenset({
    "3", "3/A", "4", "4/A", "5", "5/A",          # insider (Section 16)
    "SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A",  # beneficial ownership
    "13F-HR", "13F-HR/A", "13F-NT",              # institutional holdings, quarterly
    "13H", "13H-A", "13H-Q", "13H-R", "13H-T",   # large trader — see the note below
})
# Form 13H is filed through EDGAR but is NOT publicly disseminated: large-trader
# information is confidential under Exchange Act 13(h)(7). The forms stay in the
# allowlist because the client named them, and the poller will never see one.
# Golden case SEC-13H records that expectation so it is not rediscovered later.
SEC_FORMS_NOT_PUBLIC = frozenset({"13H", "13H-A", "13H-Q", "13H-R", "13H-T"})

ACCESSION_RE = re.compile(r"^\d{10}-\d{2}-\d{6}$")
Money = Annotated[Decimal, Field(max_digits=20, decimal_places=6)]


def is_rule612_increment(px: Decimal) -> bool:
    """SEC Rule 612 quotation increments, mirroring core.is_rule612_increment.

    Under $1.00: $0.0001. At or above: $0.01. The 2024 tick-size amendments add a
    $0.005 increment for tick-constrained NMS stocks; confirm the operative
    compliance date before relaxing this (risk A10).
    """
    if px <= 0:
        return False
    step = Decimal("0.0001") if px < Decimal("1.00") else Decimal("0.01")
    return (px % step) == 0


class QuoteSnapshot(BaseModel):
    """One fetched quote. Mirrors md.quote_snapshot so the row needs no translation."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    figi: str = Field(min_length=12, max_length=12)
    ticker: str
    bid: Optional[Money] = None
    ask: Optional[Money] = None
    bid_size: Optional[int] = Field(default=None, ge=0)
    ask_size: Optional[int] = Field(default=None, ge=0)
    last: Optional[Money] = None
    prev_close: Optional[Money] = None
    currency_code: str = Field(pattern=r"^[A-Z]{3}$")
    source: str
    delay_seconds: int = Field(ge=0)
    as_of_at_utc: datetime
    retrieved_at_utc: datetime
    session: Literal["pre", "regular", "post", "closed"]
    is_halted: Optional[bool] = None
    price_basis: Literal["adjusted", "raw"]
    unavailable_fields: tuple[str, ...] = ()

    @field_validator("bid", "ask")
    @classmethod
    def _quotes_sit_on_lawful_increments(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None and not is_rule612_increment(v):
            raise ValueError(f"{v} is not a Rule 612 quotation increment")
        return v

    @field_validator("as_of_at_utc", "retrieved_at_utc")
    @classmethod
    def _timestamps_are_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("naive timestamp: every time is timestamptz UTC")
        return v.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _venue_time_precedes_our_time(self) -> "QuoteSnapshot":
        if self.as_of_at_utc > self.retrieved_at_utc:
            raise ValueError("as_of_at_utc is after retrieved_at_utc: a quote from the future")
        return self

    @model_validator(mode="after")
    def _carries_at_least_one_price(self) -> "QuoteSnapshot":
        if self.last is None and self.bid is None and self.ask is None:
            raise ValueError("no price in the payload: this is a failed call, not an empty quote")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_crossed(self) -> Optional[bool]:
        if self.bid is None or self.ask is None:
            return None
        return self.bid > self.ask

    @computed_field  # type: ignore[prop-decorator]
    @property
    def spread_bps(self) -> Optional[Decimal]:
        """NULL on a one-sided or crossed book. 'Undefined' is an answer; a number
        computed from OHLC is a fabrication with a real timestamp on it."""
        if self.bid is None or self.ask is None or self.bid <= 0 or self.ask < self.bid:
            return None
        mid = (self.bid + self.ask) / 2
        return ((self.ask - self.bid) / mid * 10000).quantize(Decimal("0.01"))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def staleness_seconds(self) -> int:
        return int((self.retrieved_at_utc - self.as_of_at_utc).total_seconds())

    @field_serializer("bid", "ask", "last", "prev_close")
    def _money_as_string(self, v: Optional[Decimal]) -> Optional[str]:
        """A JSON float loses the tail, and the tail is where Rule 612 lives."""
        return None if v is None else str(v.quantize(Decimal("0.000001")))

    @field_serializer("as_of_at_utc", "retrieved_at_utc")
    def _ts_as_iso_z(self, v: datetime) -> str:
        return v.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class FilingRow(BaseModel):
    """One EDGAR filing. Mirrors edgar.filing."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    accession_no: str
    cik: str = Field(pattern=r"^\d{10}$")
    form_type: str
    filed_at_utc: datetime
    period_of_report: Optional[str] = None
    primary_doc_url: str

    @field_validator("accession_no")
    @classmethod
    def _accession_shape(cls, v: str) -> str:
        if not ACCESSION_RE.match(v):
            raise ValueError(f"{v!r} is not an accession number; it is the citation key, so it must be exact")
        return v

    @field_validator("form_type")
    @classmethod
    def _form_is_on_the_allowlist(cls, v: str) -> str:
        if v not in SEC_FORM_ALLOWLIST:
            raise ValueError(f"form {v!r} is outside the hardcoded allowlist (ADR-0011)")
        return v

    @field_validator("filed_at_utc")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("naive timestamp")
        return v.astimezone(timezone.utc)

    @field_serializer("filed_at_utc")
    def _ts_as_iso_z(self, v: datetime) -> str:
        return v.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class WebPriceCandidate(BaseModel):
    """One price seen on a web page during the 403 fallback.

    NOT a quote. It is a secondary report of a price, from a publisher, with an
    as-of the page asserts and we cannot verify. It carries `is_quote: False`
    frozen so nothing downstream can promote it.
    """
    model_config = ConfigDict(extra="forbid", frozen=True)

    publisher: str
    url: str
    price: Money
    as_of_text: str                       # exactly what the page said, unparsed
    as_of_at_utc: Optional[datetime] = None
    stated_delay: Optional[str] = None
    is_quote: Literal[False] = False

    @field_serializer("price")
    def _money_as_string(self, v: Decimal) -> str:
        return str(v.quantize(Decimal("0.000001")))


class WebPriceObservation(BaseModel):
    """The fallback's whole output. Deliberately not a QuoteSnapshot.

    Live evidence for why: one Exa search for NVDA returned $226.04 (Sep 8),
    $217.44 (Sep 1, 20-minute delayed) and $212.17 (Aug 25) from three reputable
    publishers. Three prices, three as-ofs, none of them a venue quote. Collapsing
    those into one number is the failure mode this whole system exists to prevent.
    """
    model_config = ConfigDict(extra="forbid", frozen=True)

    ticker: str
    figi: str
    retrieved_at_utc: datetime
    query: str
    candidates: tuple[WebPriceCandidate, ...]
    source_tier: Literal[6] = 6          # secondary report; see DATA_MODEL precedence
    writes_to_quote_table: Literal[False] = False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def spread_of_candidates_pct(self) -> Optional[Decimal]:
        if len(self.candidates) < 2:
            return None
        prices = [c.price for c in self.candidates]
        lo, hi = min(prices), max(prices)
        return ((hi - lo) / lo * 100).quantize(Decimal("0.01"))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def verdict(self) -> str:
        """INDETERMINATE unless every candidate agrees inside a tight band. The
        agent reports candidates and escalates; it never averages them."""
        if not self.candidates:
            return "INDETERMINATE"
        s = self.spread_of_candidates_pct
        if s is None:
            return "SINGLE_UNCORROBORATED"
        return "CORROBORATED" if s <= Decimal("0.50") else "INDETERMINATE"

    @field_serializer("retrieved_at_utc")
    def _ts_as_iso_z(self, v: datetime) -> str:
        return v.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
