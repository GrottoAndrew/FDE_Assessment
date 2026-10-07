"""Advisor-desk intent classification: send-as-context is a last print.

The page is the runtime, so these tests execute the same `classify()` /
`answer()` the advisor hits, extracted from the HTML.

Bare \\bsend\\b classified a live quote as client-facing output, so
"Send me NVDA's last" and
"I need to send a note, what's NVDA trading at?" returned INTERNAL USE ONLY
(BLK-005) instead of the delayed last of 226.040000.
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
    ("Send me NVDA's last", "price"),
    ("Send me the NVDA quote", "price"),
    ("Can you send me NVDA's last print?", "price"),
    ("Please send me what NVDA is trading at", "price"),
    ("Send over NVDA's last", "price"),
    ("I need to send a note, what's NVDA trading at?", "price"),
    ("After I send this, what's NVDA last?", "price"),
    ("Once I send the report, what's NVDA last?", "price"),
    ("What is NVDA trading at right now?", "price"),
    ("Draft this as an email to my client", "clientfacing"),
    ("Email this to my client", "clientfacing"),
    ("Send this to my client", "clientfacing"),
    ("Send this quote to my client", "clientfacing"),
])
def test_send_as_context_is_not_clientfacing(question, intent):
    assert classify(question) == intent


def test_send_me_returns_the_delayed_last():
    """Bare \\bsend\\b classified 'Send me NVDA's last'
    as clientfacing, so the desk answered INTERNAL USE ONLY (BLK-005)
    instead of the last print of 226.040000."""
    out = answer("Send me NVDA's last")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "INTERNAL USE ONLY" not in text
    assert "v-ok" in out["html"]
    assert not any("BLK-005" in r for r in out["rules"])


def test_send_me_the_quote_returns_the_delayed_last():
    out = answer("Send me the NVDA quote")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "INTERNAL USE ONLY" not in text


def test_need_to_send_a_note_returns_the_delayed_last():
    out = answer("I need to send a note, what's NVDA trading at?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "INTERNAL USE ONLY" not in text


def test_after_i_send_returns_the_delayed_last():
    out = answer("After I send this, what's NVDA last?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "INTERNAL USE ONLY" not in text


def test_genuine_send_asks_still_block_clientfacing():
    """A genuine send-to-client / draft-an-email ask must keep BLK-005."""
    send = answer("Send this to my client")
    assert any("BLK-005" in r for r in send["rules"])
    assert "INTERNAL USE ONLY" in _plain(send["html"])
    assert "226.040000" not in _plain(send["html"])

    send_quote = answer("Send this quote to my client")
    assert any("BLK-005" in r for r in send_quote["rules"])
    assert "INTERNAL USE ONLY" in _plain(send_quote["html"])

    draft = answer("Draft this as an email to my client")
    assert any("BLK-005" in r for r in draft["rules"])
    assert "INTERNAL USE ONLY" in _plain(draft["html"])
    assert "226.040000" not in _plain(draft["html"])
