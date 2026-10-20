"""Advisor-desk intent classification: incidental 'edgar' is a last print.

The page is the runtime, so these tests execute the same `classify()` /
`answer()` the advisor hits, extracted from the HTML.

Bare \\bedgar\\b classified a live quote as an EDGAR lookup, so
"I checked EDGAR, what's NVDA trading at?" and
"After EDGAR, what's NVDA last?" returned Form 4 accession
0001045810-26-000110 instead of the delayed last of 226.040000.
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
    ("I checked EDGAR, what's NVDA trading at?", "price"),
    ("I pulled EDGAR, what's NVDA last?", "price"),
    ("After EDGAR, what's NVDA last?", "price"),
    ("From EDGAR, what's NVDA trading at?", "price"),
    ("EDGAR aside, what's NVDA last?", "price"),
    ("That's from EDGAR, what's NVDA last?", "price"),
    ("Forget EDGAR, what's NVDA last?", "price"),
    ("EDGAR: what's NVDA last?", "price"),
    ("What's AMD last? I already checked EDGAR", "price"),
    ("What is NVDA trading at right now?", "price"),
    ("Any EDGAR filings for NVDA?", "filings"),
    ("What's on EDGAR for NVDA?", "filings"),
    ("NVDA EDGAR", "filings"),
    ("Any recent NVDA filings?", "filings"),
    ("EDGAR 13F for NVDA", "filings"),
    ("What's NVDA's last EDGAR filing?", "filings"),
])
def test_incidental_edgar_is_not_a_filing_lookup(question, intent):
    assert classify(question) == intent


def test_checked_edgar_returns_the_delayed_last():
    """Bare 'edgar' classified 'I checked EDGAR, what's NVDA trading at?'
    as filings, so the desk answered with Form 4 0001045810-26-000110
    instead of the last print of 226.040000."""
    out = answer("I checked EDGAR, what's NVDA trading at?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "0001045810-26-000110" not in text
    assert "v-ok" in out["html"]
    assert not any("filing_fact_agent" in r for r in out["rules"])


def test_after_edgar_returns_the_delayed_last():
    out = answer("After EDGAR, what's NVDA last?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "0001045810-26-000110" not in text
    assert "v-ok" in out["html"]


def test_edgar_aside_returns_the_delayed_last():
    out = answer("EDGAR aside, what's NVDA last?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "0001045810-26-000110" not in text


def test_edgar_colon_returns_the_last():
    out = answer("EDGAR: what's NVDA last?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "0001045810-26-000110" not in text


def test_genuine_edgar_lookup_still_returns_filings():
    """A direct EDGAR / filings ask must keep the EDGAR path."""
    out = answer("Any EDGAR filings for NVDA?")
    text = _plain(out["html"])
    assert any("filing_fact_agent" in r for r in out["rules"])
    assert "0001045810-26-000110" in text
    assert "226.040000" not in text

    index = answer("What's on EDGAR for NVDA?")
    assert any("filing_fact_agent" in r for r in index["rules"])
    assert "0001045810-26-000110" in _plain(index["html"])

    last_filing = answer("What's NVDA's last EDGAR filing?")
    assert any("filing_fact_agent" in r for r in last_filing["rules"])
    assert "226.040000" not in _plain(last_filing["html"])
