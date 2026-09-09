"""Advisor-desk entity resolution. The page is the runtime, so these tests
execute the same `resolve()` the advisor hits, extracted from the HTML."""
from __future__ import annotations

import json
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


def _desk_resolve_source() -> str:
    html = DESK.read_text()
    script = html.split("<script>", 1)[1].split("</script>", 1)[0]
    start = script.index("const SP500=")
    nvda_name = script.index('SP_BY_TICKER["NVDA"].name')
    nvda_end = script.index(";", nvda_name) + 1
    synonyms = script[script.index("const SYNONYMS = ") : script.index("let ACTIVE")]
    homographs_at = script.index("const HOMOGRAPHS")
    resolve_fn = _extract_function(script, "resolve")
    return "\n".join([
        script[start:nvda_end],
        synonyms,
        "const norm = s => s.toLowerCase().replace(/[^a-z0-9]/g,\"\");",
        script[homographs_at : script.index("function resolve")],
        resolve_fn,
    ])


def resolve(question: str):
    js = _desk_resolve_source() + f"\nprocess.stdout.write(JSON.stringify(resolve({json.dumps(question)})));\n"
    proc = subprocess.run(["node"], input=js, capture_output=True, text=True, cwd=ROOT)
    if proc.returncode != 0:
        raise AssertionError(f"resolve() failed to eval:\n{proc.stderr}")
    return json.loads(proc.stdout)


def _ticker(question: str) -> str | None:
    hit = resolve(question)
    return None if hit is None else hit["sp"]["ticker"]


@pytest.mark.parametrize("question,ticker", [
    ("What is NVDA trading at right now?", "NVDA"),
    ("What is AMD trading at?", "AMD"),
    ("what's aapl trading at?", "AAPL"),
    ("$IT last", "IT"),
    ("IT last", "IT"),
])
def test_an_explicit_ticker_still_resolves(question, ticker):
    assert _ticker(question) == ticker


@pytest.mark.parametrize("question,ticker", [
    ("how fast is NVDA moving?", "NVDA"),
    ("How fast is NVDA dropping today?", "NVDA"),
    ("I met with the client, what's NVDA trading at?", "NVDA"),
    ("any tech filings on NVDA?", "NVDA"),
    ("why is NVDA down today?", "NVDA"),
])
def test_an_english_word_ticker_does_not_steal_the_named_issuer(question, ticker):
    """Left-to-right first-hit rebound the rail to Fastenal / MetLife / Bio-Techne."""
    assert _ticker(question) == ticker


def test_the_dow_is_not_dow_inc_unless_the_advisor_types_the_ticker():
    """'the Dow' in a quote desk is the index, not Dow Inc. (DOW)."""
    assert _ticker("Why is the Dow down today?") is None
    assert _ticker("why is the dow down?") is None
    assert _ticker("What's DOW trading at?") == "DOW"
    assert _ticker("$DOW last") == "DOW"


def test_lowercase_it_is_not_gartner():
    assert _ticker("Why is it down today?") is None


def test_a_provisional_misspelling_still_resolves_to_nvidia():
    hit = resolve("what's nvidea trading at?")
    assert hit["sp"]["ticker"] == "NVDA"
    assert hit["kind"] == "misspelling"
    assert hit["conf"] < 0.90
