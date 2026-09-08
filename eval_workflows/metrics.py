"""
metrics.py — scoring and drift.

Scoring is deliberately strict and deliberately dumb. A fuzzy scorer that gives
partial credit produces a number that feels good and means nothing. Each case
declares its own assertion mode and we apply exactly that.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
def _get(obj: Any, key: str) -> tuple[bool, Any]:
    """Fetch `key` from a possibly-nested dict. Returns (found, value)."""
    if isinstance(obj, dict):
        if key in obj:
            return True, obj[key]
        for v in obj.values():
            found, got = _get(v, key)
            if found:
                return True, got
    return False, None


def _eq(expected: Any, actual: Any) -> bool:
    """Compare, tolerating dict subsets: expected keys must match, extras are fine."""
    if isinstance(expected, dict) and isinstance(actual, dict):
        return all(k in actual and _eq(v, actual[k]) for k, v in expected.items())
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)) \
            and not isinstance(expected, bool) and not isinstance(actual, bool):
        return abs(expected - actual) <= max(1e-9, abs(expected) * 0.001)
    return expected == actual


def score_case(case: dict, actual: dict) -> tuple[bool, str]:
    """Return (passed, human-readable detail)."""
    mode = case["assert"]
    expected = case["expect"]

    if not isinstance(actual, dict):
        return False, f"adapter returned {type(actual).__name__}, expected dict"
    if "error" in actual and "error" not in expected:
        return False, f"system errored: {actual['error']}"

    # Citation requirement is checked for every mode: an answer that is right
    # for unverifiable reasons still fails, because it cannot be audited.
    if cites := case.get("must_cite"):
        got = json.dumps(actual)
        missing = [c for c in cites if c not in got]
        if missing:
            return False, f"missing required citation(s): {missing}"

    if mode == "exact":
        for k, want in expected.items():
            if k.endswith("_min"):
                base = k[:-4]
                found, got = _get(actual, base)
                if not found:
                    return False, f"missing key '{base}'"
                if not (isinstance(got, (int, float)) and got >= want):
                    return False, f"{base}={got!r}, needed >= {want}"
                continue
            found, got = _get(actual, k)
            if not found:
                return False, f"missing key '{k}' (expected {want!r})"
            if not _eq(want, got):
                return False, f"{k}: expected {want!r}, got {got!r}"
        return True, "all expected keys matched"

    if mode == "contains":
        blob = json.dumps(actual).lower()
        misses = [f"{k}={v}" for k, v in expected.items()
                  if str(v).lower() not in blob and not _eq(v, _get(actual, k)[1])]
        return (not misses), ("substring match" if not misses
                              else f"not found in output: {misses}")

    return False, f"unknown assertion mode '{mode}' — fix the golden case"


# ---------------------------------------------------------------------------
def compare_to_baseline(summary: dict, results: list[dict], baseline_path: Path) -> dict:
    """Drift is per-case, not just aggregate.

    A run that goes 20/26 -> 20/26 while swapping which six fail is a silent
    regression that a headline pass rate hides completely.
    """
    if not baseline_path.exists():
        return {"verdict": "no baseline — run with --set-baseline to establish one"}
    try:
        base = json.loads(baseline_path.read_text())
        base_results = {}
        rp = baseline_path.parent / "results.jsonl"
        if rp.exists():
            base_results = {json.loads(l)["id"]: json.loads(l)["passed"]
                            for l in rp.read_text().splitlines() if l.strip()}
    except Exception as e:
        return {"verdict": f"baseline unreadable: {e}"}

    now = {r["id"]: r["passed"] for r in results}
    regressions = sorted(i for i, p in now.items() if base_results.get(i) and not p)
    fixes = sorted(i for i, p in now.items() if p and base_results.get(i) is False)
    new_cases = sorted(i for i in now if i not in base_results)
    dropped = sorted(i for i in base_results if i not in now)

    delta = summary["pass_rate_num"] - base.get("pass_rate_num", 0)
    if regressions:
        verdict = f"REGRESSION — {len(regressions)} case(s) newly failing ({delta:+.1%} overall)"
    elif fixes:
        verdict = f"improved — {len(fixes)} case(s) newly passing ({delta:+.1%})"
    else:
        verdict = f"stable ({delta:+.1%} vs baseline {base.get('run_id','?')})"

    return {"verdict": verdict, "delta": round(delta, 4), "regressions": regressions,
            "fixes": fixes, "new_cases": new_cases, "dropped_cases": dropped,
            "baseline_run_id": base.get("run_id")}
