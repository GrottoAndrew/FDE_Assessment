"""Advisor-desk intent classification: 'the previous call' is not the close.

The page is the runtime, so these tests execute the same `classify()` /
`answer()` the advisor hits, extracted from the HTML.

Bare \\bprevious\\b classified a live quote as prevclose, so
"From the previous call, what's NVDA last?" returned Orion's T-1
close of 230.360000 (and account ORI-4471) instead of the delayed last
of 226.040000.
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
    ("From the previous call, what's NVDA last?", "price"),
    ("Looking at the previous ticket, what's NVDA last?", "price"),
    ("The previous question — what's NVDA trading at?", "price"),
    ("From the previous call, what is NVDA trading at right now?", "price"),
    ("What is NVDA trading at right now?", "price"),
    ("What did the Wilson NVDA position close at?", "prevclose"),
    ("What was NVDA's previous close?", "prevclose"),
    ("What was the previous close on NVDA?", "prevclose"),
    ("NVDA previous close", "prevclose"),
])
def test_previous_call_is_not_the_session_close(question, intent):
    assert classify(question) == intent


def test_previous_call_still_returns_the_delayed_last():
    """Bare \\bprevious\\b classified 'From the previous call, what's NVDA last?'
    as prevclose, so the desk answered with Orion's T-1 close of 230.360000
    (and account ORI-4471) instead of the last print of 226.040000."""
    out = answer("From the previous call, what's NVDA last?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "ORI-4471" not in text
    assert "Wilson" not in text
    assert "HEU-001" not in " ".join(out["rules"])


def test_previous_ticket_still_returns_the_last():
    out = answer("Looking at the previous ticket, what's NVDA last?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "ORI-4471" not in text


def test_wilson_close_still_returns_orion():
    """The seed 'What did the Wilson NVDA position close at?' must keep
    Orion's T-1 close, and a genuine 'previous close' still is prevclose."""
    out = answer("What did the Wilson NVDA position close at?")
    text = _plain(out["html"])
    assert "230.360000" in text
    assert "ORI-4471" in text
    assert "226.040000" not in text
    assert any("HEU-001" in r for r in out["rules"])

    prev = answer("What was NVDA's previous close?")
    prev_text = _plain(prev["html"])
    assert "230.360000" in prev_text
    assert any("HEU-001" in r for r in prev["rules"])
