"""Advisor-desk intent classification: a share price is a last print.

The page is the runtime, so these tests execute the same `classify()` /
`answer()` the advisor hits, extracted from the HTML.

Bare \\bshares?\\b / \\bworth\\b / \\bvalue\\b rebound a market-data question
onto the seeded Orion row, so "what's the NVDA share price?" disclosed the
Wilson Family Trust holding instead of the delayed last.
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
    ("What's the NVDA share price?", "price"),
    ("What's NVDA's share price right now?", "price"),
    ("What's NVDA worth right now?", "price"),
    ("share the NVDA quote", "price"),
    ("What is NVDA trading at right now?", "price"),
    ("What's that position worth right now?", "position"),
    ("What's the market value of the Wilson position?", "position"),
    ("how many shares of NVDA does the account hold?", "position"),
    ("What did the Wilson NVDA position close at?", "prevclose"),
])
def test_share_price_is_a_last_print_not_a_held_quantity(question, intent):
    assert classify(question) == intent


def test_a_share_price_question_does_not_disclose_the_wilson_holding():
    """Bare \\bshares?\\b classified 'what's the NVDA share price?' as a
    position lookup, so the desk returned the Wilson Family Trust row
    (ORI-4471, 1,200 shares) instead of the delayed last of 226.040000."""
    out = answer("What's the NVDA share price?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "Wilson" not in text
    assert "1,200" not in text
    assert "ASK-207" not in " ".join(out["rules"])


def test_nvda_worth_right_now_is_the_quote_not_a_notional():
    out = answer("What's NVDA worth right now?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "Wilson" not in text
    assert "271,248" not in text


def test_a_position_question_still_returns_the_held_quantity():
    """The seed 'What's that position worth right now?' must keep ASK-207."""
    out = answer("What's that position worth right now?")
    text = _plain(out["html"])
    assert "1,200" in text
    assert "Wilson" in text
    assert any("ASK-207" in r for r in out["rules"])
