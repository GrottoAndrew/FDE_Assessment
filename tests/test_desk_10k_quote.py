"""Advisor-desk intent classification: a 10k/8k notional is a last print.

The page is the runtime, so these tests execute the same `classify()` /
`answer()` the advisor hits, extracted from the HTML.

Bare \\b10k\\b / \\b8k\\b classified a live quote as an EDGAR lookup, so
"I have 10k in NVDA, what's it trading at?" and "I put 8k in, what's
NVDA last?" returned Form 4 accession 0001045810-26-000110 instead of
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
    ("I have 10k in NVDA, what's it trading at?", "price"),
    ("What's NVDA last? Looking at 10k", "price"),
    ("Need 10k of NVDA, what's the last?", "price"),
    ("10k NVDA last?", "price"),
    ("I put 8k in NVDA, what's it trading at?", "price"),
    ("I have 10K NVDA, quote it", "price"),
    ("What's AMD last? I have 10k", "price"),
    ("What is NVDA trading at right now?", "price"),
    ("Any 10k for NVDA?", "filings"),
    ("NVDA 10-K", "filings"),
    ("form 10k for NVDA", "filings"),
    ("8-K for NVDA", "filings"),
    ("form 8k, what's NVDA last?", "filings"),
    ("Any recent NVDA filings?", "filings"),
])
def test_bare_10k_8k_amount_is_not_a_filing(question, intent):
    assert classify(question) == intent


def test_10k_in_nvda_returns_the_delayed_last():
    """Bare \\b10k\\b classified 'I have 10k in NVDA, what's it trading at?'
    as filings, so the desk answered with Form 4 0001045810-26-000110
    instead of the last print of 226.040000."""
    out = answer("I have 10k in NVDA, what's it trading at?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "0001045810-26-000110" not in text
    assert "v-ok" in out["html"]
    assert not any("filing_fact_agent" in r for r in out["rules"])


def test_looking_at_10k_returns_the_delayed_last():
    out = answer("What's NVDA last? Looking at 10k")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "0001045810-26-000110" not in text


def test_8k_in_nvda_returns_the_delayed_last():
    out = answer("I put 8k in NVDA, what's it trading at?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "0001045810-26-000110" not in text


def test_uppercase_10k_quote_still_returns_the_last():
    out = answer("I have 10K NVDA, quote it")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "0001045810-26-000110" not in text


def test_real_10k_and_8k_forms_still_return_filings():
    """A genuine 10-K / 8-K / form-10k ask must keep the EDGAR path."""
    ten_k = answer("Any 10k for NVDA?")
    assert any("filing_fact_agent" in r for r in ten_k["rules"])
    assert "0001045810-26-000110" in _plain(ten_k["html"])

    hyphen = answer("NVDA 10-K")
    assert any("filing_fact_agent" in r for r in hyphen["rules"])

    form = answer("form 10k for NVDA")
    assert any("filing_fact_agent" in r for r in form["rules"])

    eight = answer("8-K for NVDA")
    assert any("filing_fact_agent" in r for r in eight["rules"])

    form_quote = answer("form 8k, what's NVDA last?")
    assert any("filing_fact_agent" in r for r in form_quote["rules"])
    assert "226.040000" not in _plain(form_quote["html"])
