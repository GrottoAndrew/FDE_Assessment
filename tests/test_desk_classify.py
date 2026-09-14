"""Advisor-desk intent classification. The page is the runtime, so these tests
execute the same `classify()` / `answer()` the advisor hits, extracted from the HTML.

Bare English words in the classifiers rebound the answer: "can I ask what NVDA
is trading at?" became a bid/ask refusal, "what's my client's NVDA position"
became INTERNAL USE ONLY, and "forward PE" was treated as a client-facing send.
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
    ("can I ask what NVDA is trading at?", "price"),
    ("ask for the last price on NVDA", "price"),
    ("I wanted to ask about NVDA's last print", "price"),
    ("Give me the bid and ask on NVDA", "book"),
    ("what's the ask on NVDA", "book"),
    ("what's the bid on NVDA", "book"),
    ("NVDA spread", "book"),
    ("show me the book", "book"),
    ("nbbo for NVDA", "book"),
])
def test_ask_as_a_verb_is_not_the_ask_price(question, intent):
    assert classify(question) == intent


def test_asking_for_a_last_price_does_not_return_the_book_refusal():
    """Bare \\bask\\b classified 'can I ask what NVDA is trading at?' as book,
    so the desk answered INDETERMINATE about bid/ask instead of the last print."""
    out = answer("can I ask what NVDA is trading at?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "INDETERMINATE" not in text
    assert "Bid, ask and spread are unavailable" not in text


@pytest.mark.parametrize("question,intent", [
    ("What's my client's NVDA position worth?", "position"),
    ("I met with the client, what's NVDA trading at?", "price"),
    ("What's the forward PE on NVDA?", "unknown"),
    ("Draft this as an email to my client", "clientfacing"),
    ("forward this to my client", "clientfacing"),
    ("send this to my client", "clientfacing"),
    ("Should my client buy more NVDA?", "advice"),
])
def test_mentioning_a_client_is_not_a_client_facing_send(question, intent):
    assert classify(question) == intent


def test_a_client_position_question_is_not_internal_use_only():
    """Bare \\bclient\\b fired BLK-005 on 'what's my client's NVDA position',
    so the desk refused a data lookup the advisor is licensed to make."""
    out = answer("What's my client's NVDA position worth?")
    text = _plain(out["html"])
    assert "INTERNAL USE ONLY" not in text
    assert "1,200" in text
    assert "Wilson" in text
