"""Advisor-desk intent classification: 'down to' / 'calm down' is a last print.

The page is the runtime, so these tests execute the same `classify()` /
`answer()` the advisor hits, extracted from the HTML.

Bare \\bdown\\b classified a live quote as news, so "What's NVDA down to?"
and "Calm down, what's NVDA trading at?" returned a MOVE/CAUSE dump (Form 4
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
    ("What's NVDA down to?", "price"),
    ("What's NVDA down to now?", "price"),
    ("Calm down, what's NVDA trading at?", "price"),
    ("Write down NVDA's last", "price"),
    ("Sit down, what's NVDA last?", "price"),
    ("What is NVDA trading at right now?", "price"),
    ("Why is it down today?", "news"),
    ("Is NVDA down today?", "news"),
    ("Why is NVDA down?", "news"),
    ("Any recent NVDA filings?", "filings"),
])
def test_down_to_and_calm_down_are_not_a_move(question, intent):
    assert classify(question) == intent


def test_whats_nvda_down_to_returns_the_delayed_last():
    """Bare \\bdown\\b classified 'What's NVDA down to?' as news, so the desk
    answered with a MOVE/CAUSE dump (Form 4 0001045810-26-000110) instead
    of the last print of 226.040000."""
    out = answer("What's NVDA down to?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "CAUSE: UNKNOWN" not in text
    assert "0001045810-26-000110" not in text
    assert "v-ok" in out["html"]
    assert not any("macro_news_scan_agent" in r for r in out["rules"])


def test_calm_down_still_returns_the_last():
    out = answer("Calm down, what's NVDA trading at?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "CAUSE: UNKNOWN" not in text
    assert "0001045810-26-000110" not in text


def test_write_down_still_returns_the_last():
    out = answer("Write down NVDA's last")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "CAUSE: UNKNOWN" not in text


def test_why_is_it_down_still_returns_the_move():
    """The seed 'Why is it down today?' must keep the move/cause split."""
    out = answer("Why is it down today?")
    text = _plain(out["html"])
    assert "CAUSE: UNKNOWN" in text
    assert any("macro_news_scan_agent" in r for r in out["rules"])

    down = answer("Is NVDA down today?")
    assert "CAUSE: UNKNOWN" in _plain(down["html"])
    assert any("macro_news_scan_agent" in r for r in down["rules"])
