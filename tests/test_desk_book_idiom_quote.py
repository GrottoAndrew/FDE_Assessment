"""Advisor-desk intent classification: incidental 'book' is a last print.

The page is the runtime, so these tests execute the same `classify()` /
`answer()` the advisor hits, extracted from the HTML.

Bare \\bbook\\b classified a live quote as a quote-book lookup, so
"By the book, what's NVDA trading at?" and
"Book me NVDA's last" returned INDETERMINATE (bid/ask unavailable)
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
        'const fmt2 = m => (m/1e6).toLocaleString("en-US",{minimumFractionDigits:2, maximumFractionDigits:2});',
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
    ("By the book, what's NVDA trading at?", "price"),
    ("That's by the book, what's NVDA last?", "price"),
    ("By-the-book, what's NVDA last?", "price"),
    ("Book me NVDA's last", "price"),
    ("Book me NVDA's last print", "price"),
    ("In the book, what's NVDA last?", "price"),
    ("It's in the book, what's NVDA trading at?", "price"),
    ("According to the book, what's NVDA last?", "price"),
    ("The book says, what's NVDA last?", "price"),
    ("Off the book, what's NVDA last?", "price"),
    ("On the book, what's NVDA trading at?", "price"),
    ("Book: what's NVDA last?", "price"),
    ("What is NVDA trading at right now?", "price"),
    ("Give me the bid and ask on NVDA", "book"),
    ("What's the NVDA book?", "book"),
    ("Show me the quote book on NVDA", "book"),
    ("What's the order book?", "book"),
    ("Give me the NVDA book", "book"),
    ("What's the NVDA spread?", "book"),
])
def test_incidental_book_is_not_a_quote_book_lookup(question, intent):
    assert classify(question) == intent


def test_by_the_book_returns_the_delayed_last():
    """Bare 'book' classified 'By the book, what's NVDA trading at?'
    as a quote-book lookup, so the desk refused the last print of
    226.040000 and talked about bid/ask instead."""
    out = answer("By the book, what's NVDA trading at?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "INDETERMINATE" not in text
    assert "v-ok" in out["html"]
    assert not any("no quote book" in r for r in out["rules"])


def test_book_me_returns_the_delayed_last():
    out = answer("Book me NVDA's last")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "INDETERMINATE" not in text
    assert "v-ok" in out["html"]


def test_in_the_book_returns_the_delayed_last():
    out = answer("It's in the book, what's NVDA trading at?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "INDETERMINATE" not in text


def test_according_to_the_book_returns_the_delayed_last():
    out = answer("According to the book, what's NVDA last?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "INDETERMINATE" not in text


def test_book_colon_returns_the_last():
    out = answer("Book: what's NVDA last?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "INDETERMINATE" not in text


def test_genuine_book_lookup_still_refuses_bid_ask():
    """A direct quote-book ask must keep the entitled-feed refusal."""
    out = answer("What's the NVDA book?")
    text = _plain(out["html"])
    assert "Bid, ask and spread are unavailable" in text
    assert "226.040000" not in text
    assert any("no quote book" in r for r in out["rules"])

    mixed = answer("Give me the bid and ask on NVDA")
    mixed_text = _plain(mixed["html"])
    assert "Bid, ask and spread are unavailable" in mixed_text
    assert any("no quote book" in r for r in mixed["rules"])
