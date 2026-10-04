"""Advisor-desk intent classification: macro-as-context is a last print.

The page is the runtime, so these tests execute the same `classify()` /
`answer()` the advisor hits, extracted from the HTML.

Bare \\bmacro\\b classified a live quote as a move, so
"Given the macro, what's NVDA trading at?" and
"After the macro, what's NVDA last?" returned a MOVE/CAUSE dump (Form 4
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
    ("Given the macro, what's NVDA trading at?", "price"),
    ("After the macro, what's NVDA last?", "price"),
    ("I saw the macro, what's NVDA last?", "price"),
    ("I heard the macro, what's NVDA last?", "price"),
    ("I read the macro, what's NVDA last?", "price"),
    ("Despite the macro, what's NVDA last?", "price"),
    ("What is NVDA trading at right now?", "price"),
    ("Any macro on NVDA?", "news"),
    ("What's the macro on NVDA?", "news"),
    ("NVDA macro", "news"),
    ("Why is it down today?", "news"),
    ("I saw the macro", "news"),
])
def test_macro_as_context_is_not_a_move(question, intent):
    assert classify(question) == intent


def test_given_the_macro_returns_the_delayed_last():
    """Bare \\bmacro\\b classified 'Given the macro, what's NVDA trading at?'
    as news, so the desk answered with Form 4 0001045810-26-000110
    instead of the last print of 226.040000."""
    out = answer("Given the macro, what's NVDA trading at?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "0001045810-26-000110" not in text
    assert "v-ok" in out["html"]
    assert not any("macro_news_scan_agent" in r for r in out["rules"])


def test_after_the_macro_returns_the_delayed_last():
    out = answer("After the macro, what's NVDA last?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "0001045810-26-000110" not in text


def test_saw_the_macro_returns_the_delayed_last():
    out = answer("I saw the macro, what's NVDA last?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "0001045810-26-000110" not in text


def test_heard_the_macro_returns_the_delayed_last():
    out = answer("I heard the macro, what's NVDA last?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "0001045810-26-000110" not in text


def test_genuine_macro_asks_still_return_the_move():
    """A genuine macro / why-is-it-down ask must keep the MOVE/CAUSE path."""
    any_macro = answer("Any macro on NVDA?")
    assert any("macro_news_scan_agent" in r for r in any_macro["rules"])
    assert "0001045810-26-000110" in _plain(any_macro["html"])

    what = answer("What's the macro on NVDA?")
    assert any("macro_news_scan_agent" in r for r in what["rules"])

    why = answer("Why is it down today?")
    assert any("macro_news_scan_agent" in r for r in why["rules"])
    assert "226.040000" in _plain(why["html"])
