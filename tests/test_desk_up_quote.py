"""Advisor-desk intent classification: 'look up' / 'up to' is a last print.

The page is the runtime, so these tests execute the same `classify()` /
`answer()` the advisor hits, extracted from the HTML.

Bare \\bup\\b classified a live quote as news, so "What's NVDA up to?"
and "Can you look up NVDA's last?" returned a MOVE/CAUSE dump (Form 4
accession 0001045810-26-000110) instead of the delayed last of 226.040000.
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
    ("What's NVDA up to?", "price"),
    ("What's NVDA up to now?", "price"),
    ("Can you look up NVDA's last?", "price"),
    ("Look up NVDA's last print", "price"),
    ("Heads up, what's NVDA trading at?", "price"),
    ("What is NVDA trading at right now?", "price"),
    ("Why is it down today?", "news"),
    ("Is NVDA up today?", "news"),
    ("Why is NVDA up?", "news"),
    ("Any recent NVDA filings?", "filings"),
])
def test_look_up_and_up_to_are_not_a_move(question, intent):
    assert classify(question) == intent


def test_whats_nvda_up_to_returns_the_delayed_last():
    """Bare \\bup\\b classified 'What's NVDA up to?' as news, so the desk
    answered with a MOVE/CAUSE dump (Form 4 0001045810-26-000110) instead
    of the last print of 226.040000."""
    out = answer("What's NVDA up to?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "CAUSE: UNKNOWN" not in text
    assert "0001045810-26-000110" not in text
    assert "v-ok" in out["html"]
    assert not any("macro_news_scan_agent" in r for r in out["rules"])


def test_look_up_nvda_last_returns_the_delayed_last():
    out = answer("Can you look up NVDA's last?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "CAUSE: UNKNOWN" not in text
    assert "0001045810-26-000110" not in text


def test_heads_up_still_returns_the_last():
    out = answer("Heads up, what's NVDA trading at?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "CAUSE: UNKNOWN" not in text


def test_why_is_it_down_still_returns_the_move():
    """The seed 'Why is it down today?' must keep the move/cause split."""
    out = answer("Why is it down today?")
    text = _plain(out["html"])
    assert "CAUSE: UNKNOWN" in text
    assert any("macro_news_scan_agent" in r for r in out["rules"])

    up = answer("Is NVDA up today?")
    assert "CAUSE: UNKNOWN" in _plain(up["html"])
    assert any("macro_news_scan_agent" in r for r in up["rules"])
