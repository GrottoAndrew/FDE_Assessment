"""Advisor-desk resolution answers must cite the pinned issuer's CIK.

The page is the runtime, so these tests execute the same `answer()` the advisor
hits, extracted from the HTML, with `setActive` stubbed (no DOM).
"""
from __future__ import annotations

import json
import re
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


def _desk_answer_source() -> str:
    html = DESK.read_text()
    script = html.split("<script>", 1)[1].split("</script>", 1)[0]
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


def test_resolve_amd_does_not_cite_nvidias_cik():
    """`answer("resolve AMD to its CIK")` pinned AMD in the rail, then named
    NVIDIA's CIK as the canonical identifier — a sourced answer about the
    wrong issuer."""
    out = answer("resolve AMD to its CIK")
    text = _plain(out["html"])
    assert "0000002488" in text
    assert "0001045810" not in text
    assert "14 recorded variants" not in text


def test_canonical_identifier_for_intel_stays_on_intel():
    out = answer("canonical identifier for Intel")
    text = _plain(out["html"])
    assert "0000050863" in text
    assert "0001045810" not in text
    assert "Intel" in text
    assert "14 recorded variants" not in text


def test_nvda_synonym_dump_is_unchanged_on_the_seeded_slice():
    """The fat-finger demo is NVDA-only; that path still cites NVIDIA's CIK."""
    out = answer("Resolve a fat-fingered name to its CIK")
    text = _plain(out["html"])
    assert "0001045810" in text
    assert "NVIDIA" in text
    assert "14 recorded variants" in text


def test_nvidea_still_resolves_to_nvidia():
    out = answer("resolve nvidea to its CIK")
    text = _plain(out["html"])
    assert "0001045810" in text
    assert "NVIDIA" in text
    assert "0000002488" not in text
