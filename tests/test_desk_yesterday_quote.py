"""Advisor-desk intent classification: 'I asked yesterday' is not the close.

The page is the runtime, so these tests execute the same `classify()` /
`answer()` the advisor hits, extracted from the HTML.

Bare \\byesterday\\b classified a live quote as prevclose, so
"I asked yesterday, what's NVDA trading at?" returned Orion's T-1
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
    ("I asked yesterday, what's NVDA trading at?", "price"),
    ("Yesterday I needed this — what's NVDA trading at?", "price"),
    ("From yesterday's call, what's NVDA last?", "price"),
    ("I asked yesterday, what is NVDA trading at right now?", "price"),
    ("What is NVDA trading at right now?", "price"),
    ("What did the Wilson NVDA position close at?", "prevclose"),
    ("What did NVDA close at yesterday?", "prevclose"),
    ("How did NVDA do yesterday?", "prevclose"),
    ("Yesterday's NVDA close", "prevclose"),
    ("What was yesterday's close on NVDA?", "prevclose"),
])
def test_asked_yesterday_is_not_the_session_close(question, intent):
    assert classify(question) == intent


def test_asked_yesterday_still_returns_the_delayed_last():
    """Bare \\byesterday\\b classified 'I asked yesterday, what's NVDA trading at?'
    as prevclose, so the desk answered with Orion's T-1 close of 230.360000
    (and account ORI-4471) instead of the last print of 226.040000."""
    out = answer("I asked yesterday, what's NVDA trading at?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "ORI-4471" not in text
    assert "Wilson" not in text
    assert "HEU-001" not in " ".join(out["rules"])


def test_yesterday_i_needed_this_still_returns_the_last():
    out = answer("Yesterday I needed this — what's NVDA trading at?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "ORI-4471" not in text


def test_wilson_close_still_returns_orion():
    """The seed 'What did the Wilson NVDA position close at?' must keep
    Orion's T-1 close, and a genuine 'close at yesterday' still is prevclose."""
    out = answer("What did the Wilson NVDA position close at?")
    text = _plain(out["html"])
    assert "230.360000" in text
    assert "ORI-4471" in text
    assert "226.040000" not in text
    assert any("HEU-001" in r for r in out["rules"])

    yest = answer("What did NVDA close at yesterday?")
    yest_text = _plain(yest["html"])
    assert "230.360000" in yest_text
    assert any("HEU-001" in r for r in yest["rules"])
