"""Advisor-desk intent classification: email-as-context is a last print.

The page is the runtime, so these tests execute the same `classify()` /
`answer()` the advisor hits, extracted from the HTML.

Bare \\bemail\\b classified a live quote as client-facing output, so
"I got an email, what's NVDA trading at?" and
"After the email, what's NVDA last?" returned INTERNAL USE ONLY (BLK-005)
instead of the delayed last of 226.040000.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DESK = ROOT / "frontend" / "advisor_desk.html"


def _extract_function(src: str, name: str) -> str:
    idx = src.index(f"function {name}(")
    brace = src.index("{", idx)
    depth = 0
    for i, ch in enumerate(src[brace:], brace):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[idx : i + 1]
    raise AssertionError(f"unclosed function {name}")


def _script() -> str:
    html = DESK.read_text()
    return html.split("<script>", 1)[1].split("</script>", 1)[0]


def classify(question: str) -> str:
    js = (
        _extract_function(_script(), "classify")
        + f"\nprocess.stdout.write(classify({json.dumps(question)}));\n"
    )
    proc = subprocess.run(["node"], input=js, capture_output=True, text=True, cwd=ROOT)
    if proc.returncode != 0:
        raise AssertionError(f"classify() failed to eval:\n{proc.stderr}")
    return proc.stdout


def _desk_answer_source() -> str:
    script = _script()
    start = script.index("const SP500=")
    active_end = script.index("const norm =")
    homographs_at = script.index("const HOMOGRAPHS")
    return "\n".join([
        script[start:active_end],
        'const norm = s => s.toLowerCase().replace(/[^a-z0-9]/g,"");',
        "const ET = t => t;",
        "const micro = s => Math.round(parseFloat(s) * 1e6);",
        'const fmt2  = m => (m/1e6).toLocaleString("en-US",{minimumFractionDigits:2, maximumFractionDigits:2});',
        'const fmtUSD= m => "$" + fmt2(m);',
        'const edgarIssuer = cik => "https://edgar/" + cik;',
        'const edgarFiling = (cik, acc) => "https://filing/" + cik + "/" + acc;',
        "let calls = 3, CAP = 500;",
        script[homographs_at : script.index("function resolve")],
        _extract_function(script, "resolve"),
        _extract_function(script, "classify"),
        'function setActive(ticker, announce){ const sp = SP_BY_TICKER[ticker];'
        ' if (!sp) return false;'
        ' ACTIVE = {...sp, seeded: ticker === "NVDA"}; return true; }',
        _extract_function(script, "move"),
        _extract_function(script, "subject"),
        _extract_function(script, "provenance"),
        _extract_function(script, "notSeeded"),
        _extract_function(script, "answer"),
    ])


def answer(question: str, pinned: str = "NVDA"):
    js = (
        _desk_answer_source()
        + f"\nACTIVE = {{...SP_BY_TICKER[{json.dumps(pinned)}], seeded: {json.dumps(pinned == 'NVDA')}}};"
        + f"\nprocess.stdout.write(JSON.stringify(answer({json.dumps(question)})));\n"
    )
    proc = subprocess.run(["node"], input=js, capture_output=True, text=True, cwd=ROOT)
    if proc.returncode != 0:
        raise AssertionError(f"answer() failed to eval:\n{proc.stderr}")
    return json.loads(proc.stdout)


def _plain(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)


@pytest.mark.parametrize("question,intent", [
    ("I got an email, what's NVDA trading at?", "price"),
    ("After the email, what's NVDA last?", "price"),
    ("I saw the email, what's NVDA last?", "price"),
    ("I heard the email, what's NVDA last?", "price"),
    ("I received an email, what's NVDA last?", "price"),
    ("Given the email, what's NVDA last?", "price"),
    ("Despite the email, what's NVDA last?", "price"),
    ("What is NVDA trading at right now?", "price"),
    ("Draft this as an email to my client", "clientfacing"),
    ("Email this to my client", "clientfacing"),
    ("Send this to my client", "clientfacing"),
    ("Any email on NVDA?", "clientfacing"),
])
def test_email_as_context_is_not_clientfacing(question, intent):
    assert classify(question) == intent


def test_got_an_email_returns_the_delayed_last():
    """Bare \\bemail\\b classified 'I got an email, what's NVDA trading at?'
    as clientfacing, so the desk answered INTERNAL USE ONLY (BLK-005)
    instead of the last print of 226.040000."""
    out = answer("I got an email, what's NVDA trading at?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "INTERNAL USE ONLY" not in text
    assert "v-ok" in out["html"]
    assert not any("BLK-005" in r for r in out["rules"])


def test_after_the_email_returns_the_delayed_last():
    out = answer("After the email, what's NVDA last?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "INTERNAL USE ONLY" not in text


def test_saw_the_email_returns_the_delayed_last():
    out = answer("I saw the email, what's NVDA last?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "INTERNAL USE ONLY" not in text


def test_received_an_email_returns_the_delayed_last():
    out = answer("I received an email, what's NVDA last?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "INTERNAL USE ONLY" not in text


def test_genuine_email_asks_still_block_clientfacing():
    """A genuine draft-an-email / send-to-client ask must keep BLK-005."""
    draft = answer("Draft this as an email to my client")
    assert any("BLK-005" in r for r in draft["rules"])
    assert "INTERNAL USE ONLY" in _plain(draft["html"])
    assert "226.040000" not in _plain(draft["html"])

    email_client = answer("Email this to my client")
    assert any("BLK-005" in r for r in email_client["rules"])
    assert "INTERNAL USE ONLY" in _plain(email_client["html"])

    send = answer("Send this to my client")
    assert any("BLK-005" in r for r in send["rules"])
    assert "INTERNAL USE ONLY" in _plain(send["html"])
