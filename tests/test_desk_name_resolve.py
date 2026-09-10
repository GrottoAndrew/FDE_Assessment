"""Advisor-desk legal-name resolution. The page is the runtime, so these tests
execute the same `resolve()` the advisor hits, extracted from the HTML."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

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


def test_intuitive_surgical_is_not_intuit():
    """Substring includes() bound ISRG's full name to Intuit (INTU)."""
    assert _ticker("What's Intuitive Surgical trading at?") == "ISRG"
    assert _ticker("Intuitive Surgical filings") == "ISRG"
    assert _ticker("look up Intuitive Surgical on EDGAR") == "ISRG"


def test_a_full_index_name_still_resolves():
    assert _ticker("Advanced Micro Devices") == "AMD"
    assert _ticker("Apple Inc last") == "AAPL"
    assert _ticker("What is Intel trading at?") == "INTC"


def test_name_fragments_inside_ordinary_english_do_not_rebind_the_rail():
    """The concatenated-string matcher treated a shorter name as a hit inside
    an unrelated phrase, then setActive() silently pinned the wrong CIK."""
    assert _ticker("I need intelligence on why it's down") is None
    assert _ticker("any intel on the position?") is None
    assert _ticker("What's the cost comparison on the Wilson position?") is None
    assert _ticker("the position has broken the band") is None
    assert _ticker("I will fedex the paperwork") is None


def test_fedex_freight_is_not_collapsed_to_fedex():
    """Longest phrase first: FDX is a prefix of FDXF's name, not a match."""
    assert _ticker("FedEx Freight last price") == "FDXF"


def test_nvidia_synonyms_still_win_before_the_name_table():
    hit = resolve("what's nvidia trading at?")
    assert hit["sp"]["ticker"] == "NVDA"
    assert hit["kind"] == "short_name"
