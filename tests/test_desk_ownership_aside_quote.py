"""Advisor-desk intent classification: incidental 'ownership' is a last print.

The page is the runtime, so these tests execute the same `classify()` /
`answer()` the advisor hits, extracted from the HTML.

Bare \\bownership\\b classified a live quote as an ownership/filings lookup, so
"I checked ownership, what's NVDA trading at?" and
"After ownership, what's NVDA last?" returned Form 4 accession
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
    ("I checked ownership, what's NVDA trading at?", "price"),
    ("I took ownership, what's NVDA last?", "price"),
    ("Take ownership, what's NVDA last?", "price"),
    ("After ownership, what's NVDA last?", "price"),
    ("From ownership, what's NVDA trading at?", "price"),
    ("Ownership aside, what's NVDA last?", "price"),
    ("That's ownership, what's NVDA last?", "price"),
    ("Forget ownership, what's NVDA last?", "price"),
    ("Ownership: what's NVDA last?", "price"),
    ("What's AMD last? I already checked ownership", "price"),
    ("What is NVDA trading at right now?", "price"),
    ("Any ownership filings for NVDA?", "filings"),
    ("What's NVDA's ownership?", "filings"),
    ("NVDA beneficial ownership", "filings"),
    ("Any recent NVDA filings?", "filings"),
    ("Ownership 13G for NVDA", "filings"),
    ("What's NVDA's last ownership filing?", "filings"),
])
def test_incidental_ownership_is_not_a_filing_lookup(question, intent):
    assert classify(question) == intent


def test_checked_ownership_returns_the_delayed_last():
    """Bare 'ownership' classified 'I checked ownership, what's NVDA trading at?'
    as filings, so the desk answered with Form 4 0001045810-26-000110
    instead of the last print of 226.040000."""
    out = answer("I checked ownership, what's NVDA trading at?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "0001045810-26-000110" not in text
    assert "v-ok" in out["html"]
    assert not any("filing_fact_agent" in r for r in out["rules"])


def test_took_ownership_returns_the_delayed_last():
    out = answer("I took ownership, what's NVDA last?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "0001045810-26-000110" not in text
    assert "v-ok" in out["html"]


def test_after_ownership_returns_the_delayed_last():
    out = answer("After ownership, what's NVDA last?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "0001045810-26-000110" not in text
    assert "v-ok" in out["html"]


def test_ownership_aside_returns_the_delayed_last():
    out = answer("Ownership aside, what's NVDA last?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "0001045810-26-000110" not in text


def test_ownership_colon_returns_the_last():
    out = answer("Ownership: what's NVDA last?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "0001045810-26-000110" not in text


def test_genuine_ownership_lookup_still_returns_filings():
    """A direct ownership / filings ask must keep the EDGAR path."""
    out = answer("Any ownership filings for NVDA?")
    text = _plain(out["html"])
    assert any("filing_fact_agent" in r for r in out["rules"])
    assert "0001045810-26-000110" in text
    assert "226.040000" not in text

    beneficial = answer("NVDA beneficial ownership")
    assert any("filing_fact_agent" in r for r in beneficial["rules"])
    assert "0001045810-26-000110" in _plain(beneficial["html"])

    last_filing = answer("What's NVDA's last ownership filing?")
    assert any("filing_fact_agent" in r for r in last_filing["rules"])
    assert "226.040000" not in _plain(last_filing["html"])
