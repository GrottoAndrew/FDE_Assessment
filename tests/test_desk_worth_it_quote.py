"""Advisor-desk intent classification: incidental 'worth it' is a last print.

The page is the runtime, so these tests execute the same `classify()` /
`answer()` the advisor hits, extracted from the HTML.

Bare "worth it" classified a live quote as BLK-003 advice, so
"That's worth it, what's NVDA trading at?" and
"Worth it, what's NVDA last?" returned CANNOT ANSWER
instead of the delayed last of 226.040000.
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
    ("That's worth it, what's NVDA trading at?", "price"),
    ("That is worth it, what's NVDA last?", "price"),
    ("Sounds worth it, what's NVDA trading at?", "price"),
    ("Sounds like it's worth it, what's NVDA last?", "price"),
    ("It's worth it to check, what's NVDA trading at?", "price"),
    ("Worth it to look, what's NVDA last?", "price"),
    ("I thought it was worth it, what's NVDA last?", "price"),
    ("Worth it, what's NVDA trading at?", "price"),
    ("Worth it. What's NVDA last?", "price"),
    ("What's NVDA last? Worth it.", "price"),
    ("What's NVDA last? That's worth it.", "price"),
    ("If it's worth it, what's NVDA last?", "price"),
    ("What is NVDA trading at right now?", "price"),
    ("Is NVDA worth it?", "advice"),
    ("Is NVDA worth buying?", "advice"),
    ("Is it worth buying NVDA?", "advice"),
    ("Should my client buy more NVDA?", "advice"),
    ("Is NVDA worth it, what's it trading at?", "advice"),
])
def test_incidental_worth_it_is_not_a_recommendation(question, intent):
    assert classify(question) == intent


def test_thats_worth_it_returns_the_delayed_last():
    """Bare 'worth it' classified 'That's worth it, what's NVDA trading at?'
    as BLK-003, so the desk refused the last print of 226.040000."""
    out = answer("That's worth it, what's NVDA trading at?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "CANNOT ANSWER" not in text
    assert "Wilson Family Trust" not in text
    assert "ORI-4471" not in text
    assert "v-ok" in out["html"]
    assert not any("BLK-003" in r for r in out["rules"])


def test_worth_it_comma_returns_the_delayed_last():
    out = answer("Worth it, what's NVDA trading at?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "CANNOT ANSWER" not in text
    assert "Wilson Family Trust" not in text


def test_sounds_worth_it_returns_the_delayed_last():
    out = answer("Sounds worth it, what's NVDA trading at?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "CANNOT ANSWER" not in text
    assert "Wilson Family Trust" not in text


def test_worth_it_to_check_returns_the_delayed_last():
    out = answer("It's worth it to check, what's NVDA trading at?")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "CANNOT ANSWER" not in text
    assert "Wilson Family Trust" not in text


def test_trailing_worth_it_returns_the_last():
    out = answer("What's NVDA last? Worth it.")
    text = _plain(out["html"])
    assert "226.040000" in text
    assert "CANNOT ANSWER" not in text
    assert "Wilson Family Trust" not in text


def test_is_nvda_worth_it_still_blocks():
    """A direct worth-it / worth-buying ask must keep BLK-003."""
    out = answer("Is NVDA worth it?")
    text = _plain(out["html"])
    assert "CANNOT ANSWER" in text
    assert "226.040000" not in text
    assert any("BLK-003" in r for r in out["rules"])

    buy = answer("Is NVDA worth buying?")
    assert "CANNOT ANSWER" in _plain(buy["html"])
    assert "226.040000" not in _plain(buy["html"])
    assert any("BLK-003" in r for r in buy["rules"])

    mixed = answer("Is NVDA worth it, what's it trading at?")
    assert "CANNOT ANSWER" in _plain(mixed["html"])
    assert "226.040000" not in _plain(mixed["html"])
    assert any("BLK-003" in r for r in mixed["rules"])
