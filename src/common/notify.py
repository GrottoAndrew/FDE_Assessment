"""
notify.py — outbound alerts, with no silent path.

A notification that fails to send and says nothing is worse than no notification
at all: the desk believes the CCO was told. Every send either succeeds, or raises
and the caller writes ops.failure_log.

No SMTP is configured in the prototype. The default transport prints to stderr
and returns a receipt, so the notification is observable and the wiring is real;
swapping in SMTP or the firm's alerting bus is one class.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

# PLACEHOLDER — replace with the firm's real Chief Compliance Officer alias.
CCO_ALERT_EMAIL = "cco-alerts@placeholder-ibd.example"
OPS_ALERT_EMAIL = "market-data-ops@placeholder-ibd.example"


@dataclass(frozen=True)
class Notification:
    to: str
    subject: str
    body: str
    severity: str                      # 'info' | 'warning' | 'critical'
    event_type: str                    # 'trading_halt' | 'stale_data' | ...
    figi: str | None = None
    evidence: dict = field(default_factory=dict)
    created_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def render(self) -> str:
        lines = [f"To: {self.to}", f"Subject: {self.subject}",
                 f"Severity: {self.severity}", f"Event: {self.event_type}",
                 f"At: {self.created_at_utc.isoformat().replace('+00:00', 'Z')}", ""]
        if self.figi:
            lines.append(f"Security: {self.figi}")
        lines.append(self.body)
        if self.evidence:
            lines.append("")
            lines.append("Evidence:")
            lines += [f"  {k}: {v}" for k, v in sorted(self.evidence.items())]
        return "\n".join(lines)


class Transport(Protocol):
    def send(self, n: Notification) -> str: ...


class StderrTransport:
    """Default. Observable, never silent, and obviously not production email."""
    def send(self, n: Notification) -> str:
        print("=" * 68, file=sys.stderr)
        print(n.render(), file=sys.stderr)
        print("=" * 68, file=sys.stderr)
        return f"stderr:{n.event_type}:{n.created_at_utc.timestamp()}"


class RecordingTransport:
    """Test double. Keeps what was sent so a test can assert on it."""
    def __init__(self) -> None:
        self.sent: list[Notification] = []

    def send(self, n: Notification) -> str:
        self.sent.append(n)
        return f"recorded:{len(self.sent)}"


def halt_notice(figi: str, ticker: str, evidence: dict,
                transport: Transport | None = None) -> str:
    """Tell the CCO a security the desk is quoting has stopped trading.

    Sent on the halt, not on the resumption: the window where an advisor might
    quote a halted name is exactly the window between those two events.
    """
    n = Notification(
        to=CCO_ALERT_EMAIL,
        subject=f"[HALT] {ticker} — trading halted, desk quoting suspended",
        body=(f"{ticker} ({figi}) is reported halted. The quote agent is returning "
              "INDETERMINATE for this security and will not serve a last price as "
              "current. No advisor-facing quote has been issued from the halted state."),
        severity="critical", event_type="trading_halt", figi=figi, evidence=evidence)
    return (transport or StderrTransport()).send(n)
