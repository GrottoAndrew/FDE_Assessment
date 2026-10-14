"""Advisor-desk intent classification: incidental 'position' is a last print.

The page is the runtime, so these tests execute the same `classify()` /
`answer()` the advisor hits, extracted from the HTML.

Bare \\bpositions?\\b classified a live quote as a holdings lookup, so
"I'm not in a position to wait, what's NVDA trading at?" and
"Given NVDA's position, what's it trading at?" disclosed the Wilson
Family Trust holding (account ORI-4471, 1,200 shares, $271,248 notional)
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
    ("I'm not in a position to wait, what's NVDA trading at?", "price"),
    ("I am not in a position to wait, what's NVDA last?", "price"),
    ("In a position to check, what's NVDA last?", "price"),
    ("I'm in a position to look, what's NVDA trading at?", "price"),
    ("We're in no position to wait, what's NVDA last?", "price"),
    ("Given NVDA's position, what's it trading at?", "price"),
    ("Given NVIDIA's position, what's it last?", "price"),
    ("Given their position, what's NVDA last?", "price"),
    ("NVIDIA's market position aside, what's it trading at?", "price"),
    ("Competitive position aside, what's NVDA last?", "price"),
    ("Take a position: what's NVDA last?", "price"),
    ("What is NVDA trading at right now?", "price"),
    ("What's that position worth right now?", "position"),
    ("What's the NVDA position?", "position"),
    ("What's my NVDA position, what's it trading at?", "position"),
])
def test_incidental_position_is_not_a_holdings_lookup(question, intent):
    assert classify(question) == intent


def test_not_in_a_position_returns_the_delayed_last():
    """Bare 'position' classified 'I'm not in a position to wait, what's
    NVDA trading at?' as a holdings lookup, so the desk disclosed the
    Wilson Family Trust holding instead of the last print of 226.040000."""
    out = answer("I'm not in a position to wait, what's NVDA trading at?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "Wilson Family Trust" not in text
    assert "ORI-4471" not in text
    assert "1,200" not in text
    assert "v-ok" in out["html"]
    assert not any("ASK-207" in r for r in out["rules"])


def test_in_a_position_to_check_returns_the_delayed_last():
    out = answer("In a position to check, what's NVDA last?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "Wilson Family Trust" not in text
    assert "ORI-4471" not in text


def test_given_nvda_position_returns_the_delayed_last():
    out = answer("Given NVDA's position, what's it trading at?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "Wilson Family Trust" not in text
    assert "ORI-4471" not in text


def test_market_position_aside_returns_the_delayed_last():
    out = answer("NVIDIA's market position aside, what's it trading at?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "Wilson Family Trust" not in text
    assert "ORI-4471" not in text


def test_take_a_position_returns_the_last():
    out = answer("Take a position: what's NVDA last?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "Wilson Family Trust" not in text
    assert "ORI-4471" not in text


def test_genuine_position_lookup_still_discloses_the_holding():
    """A direct position ask must keep the Orion holding and ASK-207."""
    out = answer("What's that position worth right now?")
    text = _plain(out["html"])
    assert "Wilson Family Trust" in text
    assert "ORI-4471" in text
    assert "1,200" in text
    assert any("ASK-207" in r for r in out["rules"])

    mixed = answer("What's my NVDA position, what's it trading at?")
    mixed_text = _plain(mixed["html"])
    assert "Wilson Family Trust" in mixed_text
    assert "ORI-4471" in mixed_text
    assert any("ASK-207" in r for r in mixed["rules"])
