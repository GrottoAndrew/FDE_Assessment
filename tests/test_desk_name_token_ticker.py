"""A shorter ticker that is only a token of a longer index name must not
rebind the rail to a different issuer.

The page is the runtime, so these tests execute the same `resolve()` the
advisor hits, extracted from the HTML.
"""
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
    ("What is GE Vernova trading at?", "GEV"),
    ("What is GE HealthCare trading at?", "GEHC"),
    ("What is T Rowe Price trading at?", "TROW"),
    ("What is T. Rowe Price trading at?", "TROW"),
    ("What is A O Smith trading at?", "AOS"),
    ("What is A. O. Smith trading at?", "AOS"),
    ("What is C H Robinson trading at?", "CHRW"),
    ("What is T Mobile US trading at?", "TMUS"),
    ("What is D. R. Horton trading at?", "DHI"),
    ("What is J.B. Hunt trading at?", "JBHT"),
    ("What is O'Reilly Automotive trading at?", "ORLY"),
])
def test_a_longer_index_name_beats_a_shorter_name_token_ticker(question, ticker):
    assert _ticker(question) == ticker


@pytest.mark.parametrize("question,ticker", [
    ("What is GE trading at?", "GE"),
    ("What is T trading at?", "T"),
    ("What is A trading at?", "A"),
    ("What is C trading at?", "C"),
    ("What is NVDA trading at right now?", "NVDA"),
    ("What is AMD trading at?", "AMD"),
])
def test_a_bare_ticker_still_resolves_to_that_issuer(question, ticker):
    assert _ticker(question) == ticker


def test_ge_vernova_is_not_ge_aerospace():
    hit = resolve("What is GE Vernova trading at?")
    assert hit["sp"]["ticker"] == "GEV"
    assert hit["sp"]["cik"] == "0001996810"
    assert hit["sp"]["cik"] != "0000040545"


def test_t_rowe_price_is_not_att():
    hit = resolve("What is T Rowe Price trading at?")
    assert hit["sp"]["ticker"] == "TROW"
    assert hit["sp"]["cik"] == "0001113169"
    assert hit["sp"]["cik"] != "0000732717"
