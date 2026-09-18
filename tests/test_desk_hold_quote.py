"""Advisor-desk intent classification: 'hold on' is not a position lookup.

The page is the runtime, so these tests execute the same `classify()` /
`answer()` the advisor hits, extracted from the HTML.

Bare hold(ing)?s? classified a live quote as position, so
"Hold on, what's NVDA trading at?" returned the Wilson Family Trust
holding (account ORI-4471, 1,200 shares, $271,248 notional) instead of
the delayed last of 226.040000.
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
    ("Hold on, what's NVDA trading at?", "price"),
    ("Please hold, what's NVDA trading at?", "price"),
    ("Can you hold, what's the NVDA last?", "price"),
    ("Hold please — what is NVDA trading at right now?", "price"),
    ("I hold NVDA, what's it trading at?", "price"),
    ("What is NVDA trading at right now?", "price"),
    ("What's the NVDA holding?", "position"),
    ("What are the holdings in NVDA?", "position"),
    ("What's that position worth right now?", "position"),
    ("What's the NVDA notional?", "position"),
])
def test_hold_as_a_pause_is_not_a_position(question, intent):
    assert classify(question) == intent


def test_hold_on_still_returns_the_delayed_last():
    """Bare hold(ing)?s? classified 'Hold on, what's NVDA trading at?'
    as position, so the desk disclosed the Wilson Family Trust holding
    (ORI-4471, 1,200 shares) instead of the last print of 226.040000."""
    out = answer("Hold on, what's NVDA trading at?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "ORI-4471" not in text
    assert "Wilson Family Trust" not in text
    assert "1,200" not in text
    assert "ASK-207" not in " ".join(out["rules"])


def test_please_hold_still_returns_the_last():
    out = answer("Please hold, what's NVDA trading at?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "ORI-4471" not in text
    assert "Wilson Family Trust" not in text


def test_holding_noun_still_returns_the_position():
    """'What's the NVDA holding?' and the seed 'What's that position worth
    right now?' must keep ASK-207 and the Orion quantity."""
    out = answer("What's the NVDA holding?")
    text = _plain(out["html"])
    assert "Wilson Family Trust" in text
    assert "1,200" in text
    assert "ORI-4471" in text
    assert "226.040000" not in text
    assert any("ASK-207" in r for r in out["rules"])

    seed = answer("What's that position worth right now?")
    seed_text = _plain(seed["html"])
    assert "Wilson Family Trust" in seed_text
    assert any("ASK-207" in r for r in seed["rules"])
