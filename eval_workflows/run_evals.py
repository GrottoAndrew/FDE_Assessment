#!/usr/bin/env python3
"""
run_evals.py — run the golden set against the system under test.

Day 1 this runs against a stub adapter so the whole pipeline (load -> run ->
score -> drift -> report) is proven before any agent exists. On sprint day you
implement ONE function, `SystemAdapter.invoke`, and everything downstream works.

    make eval              # full golden set
    make evalq             # smoke tier only
    python3 eval_workflows/run_evals.py --tier core --baseline eval_output/baseline

Writes eval_output/<run_id>/{summary.json,results.jsonl,report.md} and compares
against a baseline so deviation over time is visible rather than remembered.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eval_workflows.metrics import compare_to_baseline, score_case  # noqa: E402


# ---------------------------------------------------------------------------
# THE ONLY THING YOU IMPLEMENT ON SPRINT DAY
# ---------------------------------------------------------------------------
class SystemAdapter:
    """Wraps the system under test. Keep the eval harness ignorant of it."""

    def __init__(self, mode: str = "stub"):
        self.mode = mode

    def invoke(self, case: dict) -> dict:
        """Return the system's actual output for one golden case.

        Contract: return a flat-ish dict. Include 'error' on failure. Never
        raise — a crash is a result, and the harness records it as one.
        """
        if self.mode == "stub":
            return self._stub(case)
        raise NotImplementedError(
            "Implement SystemAdapter.invoke: route `case['input']` to the "
            "orchestrator for `case['agent']` and return its output dict."
        )

    @staticmethod
    def _stub(case: dict) -> dict:
        """Echoes the expectation so the harness is exercised end to end.

        Deliberately imperfect: it fails the adversarial case so a fresh run
        never shows a misleading 100%.
        """
        if case.get("tier") == "adversarial":
            return {"verdict": "SUPPORTED", "_stub": True}   # wrong on purpose
        out = dict(case.get("expect", {}))
        out["_stub"] = True
        return out


# ---------------------------------------------------------------------------
def load_golden(path: Path, tier: str | None, agent: str | None) -> list[dict]:
    cases = []
    for i, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            c = json.loads(line)
        except json.JSONDecodeError as e:
            raise SystemExit(f"{path}:{i} is not valid JSON: {e}")
        for req in ("id", "tier", "agent", "input", "expect", "assert"):
            if req not in c:
                raise SystemExit(f"{path}:{i} case missing required field '{req}'")
        if tier and c["tier"] != tier:
            continue
        if agent and c["agent"] not in (agent, "*"):
            continue
        cases.append(c)
    if not cases:
        raise SystemExit("No cases matched the filter — refusing to report a vacuous pass.")
    return cases


def run(cases: list[dict], adapter: SystemAdapter) -> list[dict]:
    results = []
    for c in cases:
        t0 = time.perf_counter()
        try:
            actual = adapter.invoke(c)
            err = None
        except Exception as e:                      # adapter contract violation
            actual, err = {}, f"{type(e).__name__}: {e}"
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)

        passed, detail = (False, f"adapter raised: {err}") if err else score_case(c, actual)
        results.append({
            "id": c["id"], "tier": c["tier"], "agent": c["agent"],
            "category": c.get("category", "uncategorized"),
            "passed": passed, "detail": detail,
            "expected": c["expect"], "actual": actual,
            "latency_ms": latency_ms, "why": c.get("why", ""),
        })
        print(f"  {'PASS' if passed else 'FAIL'}  {c['id']:<10} {c.get('category','')}"
              + ("" if passed else f"\n         -> {detail}"))
    return results


def summarize(results: list[dict], run_id: str, mode: str) -> dict:
    total, passed = len(results), sum(r["passed"] for r in results)
    lat = sorted(r["latency_ms"] for r in results)
    by_cat: dict[str, dict] = {}
    for r in results:
        b = by_cat.setdefault(r["category"], {"total": 0, "passed": 0})
        b["total"] += 1
        b["passed"] += r["passed"]

    # Safety categories are reported separately: an overall 90% that hides a
    # failed gate test is not a passing system.
    SAFETY = {"gate_block", "gate_persistence", "ceiling_rule",
              "least_privilege", "fail_loud", "no_send_capability"}
    safety = [r for r in results if r["category"] in SAFETY]

    return {
        "run_id": run_id,
        "ts_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "adapter_mode": mode,
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": f"{passed / total:.1%}",
        "pass_rate_num": round(passed / total, 4),
        "safety_total": len(safety),
        "safety_passed": sum(r["passed"] for r in safety),
        "safety_clean": all(r["passed"] for r in safety),
        "latency_p50_ms": lat[len(lat) // 2] if lat else 0,
        "latency_p95_ms": lat[int(len(lat) * 0.95) - 1] if len(lat) > 1 else (lat[0] if lat else 0),
        "latency_mean_ms": round(statistics.mean(lat), 2) if lat else 0,
        "by_category": {k: {**v, "pass_rate": f"{v['passed'] / v['total']:.0%}"}
                        for k, v in sorted(by_cat.items())},
        "failed_ids": [r["id"] for r in results if not r["passed"]],
    }


def write_report(outdir: Path, summary: dict, results: list[dict], drift: dict) -> None:
    fails = [r for r in results if not r["passed"]]
    lines = [
        f"# Eval run `{summary['run_id']}`", "",
        f"- **{summary['passed']}/{summary['total']} passed** ({summary['pass_rate']})",
        f"- Safety categories: {summary['safety_passed']}/{summary['safety_total']}"
        + ("  ✅ clean" if summary["safety_clean"] else "  ❌ **A SAFETY TEST FAILED**"),
        f"- Latency p50 {summary['latency_p50_ms']}ms / p95 {summary['latency_p95_ms']}ms",
        f"- Adapter: `{summary['adapter_mode']}`"
        + ("  ⚠️ STUB — these numbers describe the harness, not a system."
           if summary["adapter_mode"] == "stub" else ""),
        "", "## Drift vs baseline", "",
        f"{drift.get('verdict', 'no baseline')}", "",
    ]
    if drift.get("regressions"):
        lines += ["**Newly failing:** " + ", ".join(drift["regressions"]), ""]
    if drift.get("fixes"):
        lines += ["**Newly passing:** " + ", ".join(drift["fixes"]), ""]
    lines += ["## By category", "", "| category | pass | total | rate |", "|---|---|---|---|"]
    lines += [f"| {k} | {v['passed']} | {v['total']} | {v['pass_rate']} |"
              for k, v in summary["by_category"].items()]
    if fails:
        lines += ["", "## Failures", ""]
        for r in fails:
            lines += [f"### `{r['id']}` — {r['category']}",
                      f"- **Why this case exists:** {r['why']}",
                      f"- **Detail:** {r['detail']}",
                      f"- Expected: `{json.dumps(r['expected'])}`",
                      f"- Actual: `{json.dumps(r['actual'])}`", ""]
    (outdir / "report.md").write_text("\n".join(lines))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", default=os.environ.get(
        "EVAL_GOLDEN_PATH", "eval_workflows/golden/golden_set.jsonl"))
    ap.add_argument("--tier", choices=["smoke", "core", "extended", "adversarial"])
    ap.add_argument("--agent")
    ap.add_argument("--mode", default="stub", help="stub | live")
    ap.add_argument("--outdir", default=os.environ.get("EVAL_OUTPUT_DIR", "eval_output"))
    ap.add_argument("--baseline", default="eval_output/baseline/summary.json")
    ap.add_argument("--set-baseline", action="store_true")
    a = ap.parse_args()

    cases = load_golden(ROOT / a.golden, a.tier, a.agent)
    run_id = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
    print(f"\nrun {run_id} — {len(cases)} cases, adapter={a.mode}\n")

    results = run(cases, SystemAdapter(a.mode))
    summary = summarize(results, run_id, a.mode)
    drift = compare_to_baseline(summary, results, ROOT / a.baseline)
    summary["drift"] = drift.get("verdict", "no baseline")

    outdir = ROOT / a.outdir / run_id
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "summary.json").write_text(json.dumps(summary, indent=2))
    with (outdir / "results.jsonl").open("w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")
    write_report(outdir, summary, results, drift)

    if a.set_baseline:
        base = ROOT / a.outdir / "baseline"
        base.mkdir(parents=True, exist_ok=True)
        (base / "summary.json").write_text(json.dumps(summary, indent=2))
        with (base / "results.jsonl").open("w") as f:
            for r in results:
                f.write(json.dumps(r) + "\n")
        print(f"\nbaseline set -> {base}")

    print(f"\n{summary['passed']}/{summary['total']} passed ({summary['pass_rate']})")
    print(f"drift: {summary['drift']}")
    print(f"report: {(outdir / 'report.md').relative_to(ROOT)}")
    if not summary["safety_clean"]:
        print("\nSAFETY TEST FAILED — do not demo this build.")
        return 2
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
