"""
pull_guard.py — what has to be true before a price reaches an advisor.

The order matters, and each step is cheaper than the one after it:

  1. CLOCK      Is the regular session open, on the NYSE clock? If not, no call
                is made at all. Roughly two thirds of a 24-hour schedule is
                outside regular hours, so this is the largest single saving in
                the budget and it is free.
  2. FETCH      One attempt.
  3. SECOND     Empty or invalid gets exactly one re-check (retry.yaml allows
     CHECK      1 + 1). A source that returns nothing twice is not flaky.
  4. COMPARE    Two good reads that disagree by more than the tolerance are not
                averaged and not "latest wins". They are INDETERMINATE and they
                go to triage, because one of them is wrong and nothing here can
                say which.
  5. HALT       A halted security returns INDETERMINATE and the CCO is notified.
                A last print from a halted book is not a current price, and the
                window between the halt and its resumption is exactly the window
                where an advisor would quote it to a client.

Every terminal state is either a validated quote or an explicit refusal. There
is no branch that returns a plausible number.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Callable, Optional, Protocol

from src.common.market_clock import ClockReading, Session
from src.common.market_clock import reading as clock_reading
from src.common.market_models import QuoteSnapshot
from src.common.notify import Transport, halt_notice

# Two reads of the same security inside seconds should agree. Anything wider is
# a data problem, not market movement.
DEFAULT_TOLERANCE_PCT = Decimal("0.50")


class Outcome(str, Enum):
    OK = "OK"
    SKIPPED_MARKET_CLOSED = "SKIPPED_MARKET_CLOSED"
    INDETERMINATE_HALTED = "INDETERMINATE_HALTED"
    INDETERMINATE_DISAGREEMENT = "INDETERMINATE_DISAGREEMENT"
    FAILED_NO_DATA = "FAILED_NO_DATA"


class HaltStatus(str, Enum):
    TRADING = "trading"
    HALTED = "halted"
    UNKNOWN = "unknown"      # the interim source does not report it


class HaltCheck(Protocol):
    def status(self, figi: str) -> HaltStatus: ...


class UnavailableHaltCheck:
    """The default, and an honest one.

    The interim chart source carries no halt field, so halt state is UNKNOWN, not
    False. A quote produced under UNKNOWN is returned with halt_verified=False and
    the desk must say so. Asserting "trading normally" from a source that cannot
    know it is the same class of error as inventing a price.
    """
    def status(self, figi: str) -> HaltStatus:
        return HaltStatus.UNKNOWN


@dataclass(frozen=True)
class PullResult:
    outcome: Outcome
    quote: Optional[QuoteSnapshot] = None
    attempts: int = 0
    calls_spent: int = 0
    halt_verified: bool = False
    triage_class: Optional[str] = None
    reason: str = ""
    evidence: dict = field(default_factory=dict)

    @property
    def is_servable(self) -> bool:
        return self.outcome is Outcome.OK


def _pct_delta(a: Decimal, b: Decimal) -> Decimal:
    if a == 0:
        return Decimal("100")
    return (abs(b - a) / a * 100).quantize(Decimal("0.0001"))


def guarded_pull(
    fetch: Callable[[], Optional[QuoteSnapshot]],
    figi: str,
    ticker: str,
    now: datetime | None = None,
    clock: ClockReading | None = None,
    halt_check: HaltCheck | None = None,
    tolerance_pct: Decimal = DEFAULT_TOLERANCE_PCT,
    transport: Transport | None = None,
    verify: bool = True,
) -> PullResult:
    """Run the gate sequence. `fetch` returns a validated QuoteSnapshot or None.

    `fetch` raising is treated the same as returning None: a payload that failed
    schema validation is no data, not partial data.

    `verify` controls step 4 only. The re-check on NO DATA is unconditional and
    costs a call only when something already went wrong. The verification read on
    GOOD data doubles the call cost of every successful pull, which a 15-minute
    schedule cannot afford: it takes 567 calls a month to 1,134. So it is ON for
    advisor-facing requests, where a wrong price is read out to a client, and OFF
    for scheduled polling, where the next tick fifteen minutes later is the check.
    """
    clock = clock or clock_reading(now)

    # 1. CLOCK — before spending anything.
    if not clock.may_fetch_current_quote:
        return PullResult(
            outcome=Outcome.SKIPPED_MARKET_CLOSED, attempts=0, calls_spent=0,
            reason=f"{clock.reason}; no current quote exists to fetch",
            evidence={"session": clock.session.value, "et": clock.now_et.isoformat(),
                      "trade_date": str(clock.trade_date),
                      "calendar_verified": clock.calendar_verified})

    def _try() -> Optional[QuoteSnapshot]:
        try:
            return fetch()
        except Exception:
            return None       # a validation failure is no data; the caller logs it

    # 2/3. FETCH, then exactly one SECOND CHECK on empty or invalid.
    first = _try()
    attempts, spent = 1, 1
    if first is None:
        second = _try()
        attempts, spent = 2, 2
        if second is None:
            return PullResult(
                outcome=Outcome.FAILED_NO_DATA, attempts=attempts, calls_spent=spent,
                triage_class="source_unavailable",
                reason="two consecutive reads returned no usable data",
                evidence={"session": clock.session.value})
        first = second       # the re-check succeeded; use it, and do not compare
        # a single good read after an empty one has nothing to compare against
        return _finish(first, figi, ticker, attempts, spent, halt_check, transport,
                       evidence={"recovered_on_second_check": True})

    # 4. COMPARE — a second read of a good first read, to catch incorrect data.
    if not verify:
        return _finish(first, figi, ticker, attempts, spent, halt_check, transport,
                       evidence={"verified": False})
    second = _try()
    attempts, spent = 2, 2
    if second is None:
        return PullResult(
            outcome=Outcome.INDETERMINATE_DISAGREEMENT, attempts=attempts, calls_spent=spent,
            triage_class="unstable_source", quote=None,
            reason="first read succeeded, verification read returned nothing",
            evidence={"first_last": str(first.last)})

    a, b = first.last, second.last
    if a is None or b is None:
        delta = Decimal("100")
    else:
        delta = _pct_delta(a, b)
    if delta > tolerance_pct:
        return PullResult(
            outcome=Outcome.INDETERMINATE_DISAGREEMENT, attempts=attempts, calls_spent=spent,
            triage_class="source_disagreement", quote=None,
            reason=f"two reads differ by {delta}%, over the {tolerance_pct}% tolerance",
            evidence={"first_last": str(a), "second_last": str(b), "delta_pct": str(delta)})

    return _finish(second, figi, ticker, attempts, spent, halt_check, transport,
                   evidence={"delta_pct": str(delta)})


def _finish(quote: QuoteSnapshot, figi: str, ticker: str, attempts: int, spent: int,
            halt_check: HaltCheck | None, transport: Transport | None,
            evidence: dict) -> PullResult:
    # 5. HALT — last, because it is the only step that sends mail.
    status = (halt_check or UnavailableHaltCheck()).status(figi)
    if status is HaltStatus.HALTED:
        ev = {**evidence, "last_seen": str(quote.last),
              "as_of_at_utc": quote.as_of_at_utc.isoformat()}
        receipt = halt_notice(figi, ticker, ev, transport)
        return PullResult(
            outcome=Outcome.INDETERMINATE_HALTED, quote=None, attempts=attempts,
            calls_spent=spent, halt_verified=True, triage_class="trading_halt",
            reason="security is halted; a last print is not a current price",
            evidence={**ev, "cco_notice_receipt": receipt})

    return PullResult(
        outcome=Outcome.OK, quote=quote, attempts=attempts, calls_spent=spent,
        halt_verified=(status is HaltStatus.TRADING),
        reason="verified by a second read" if attempts == 2 else "single read",
        evidence={**evidence, "halt_status": status.value})
