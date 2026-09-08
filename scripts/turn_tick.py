#!/usr/bin/env python3
"""
turn_tick.py — fires on every UserPromptSubmit (see .claude/settings.json).

Increments a turn counter. On every 5th turn it regenerates
docs/presentation/PRESENTATION_PROMPT.txt by scraping live repo state, so the
deck prompt is never more than 5 turns stale. Run `make deck` to force it.

Exit code is always 0: a failure here must never block the sprint.
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR", Path(__file__).resolve().parent.parent))
COUNTER = ROOT / ".claude" / "turn_counter"
OUT = ROOT / "docs" / "presentation" / "PRESENTATION_PROMPT.txt"
EVERY = 5


def sh(cmd, default=""):
    try:
        return subprocess.run(
            cmd, cwd=ROOT, shell=True, capture_output=True, text=True, timeout=8
        ).stdout.strip() or default
    except Exception:
        return default


def bump():
    COUNTER.parent.mkdir(parents=True, exist_ok=True)
    try:
        n = int(COUNTER.read_text().strip()) + 1
    except Exception:
        n = 1
    COUNTER.write_text(str(n))
    return n


def bullets(lines, empty="  (none yet)"):
    return "\n".join(f"  - {l}" for l in lines) if lines else empty


def collect():
    s = {}
    s["ts"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    s["branch"] = sh("git rev-parse --abbrev-ref HEAD", "main")
    s["commits"] = [l for l in sh("git log --oneline -12").splitlines() if l]
    s["changed"] = [l for l in sh("git status --porcelain").splitlines() if l][:25]

    # ADRs: title + status
    adrs = []
    for p in sorted((ROOT / "docs" / "adr").glob("[0-9]*.md")):
        txt = p.read_text(errors="ignore")
        title = next((l.lstrip("# ").strip() for l in txt.splitlines() if l.startswith("# ")), p.stem)
        status = next((l.split(":", 1)[1].strip() for l in txt.splitlines()
                       if l.lower().startswith("status:")), "?")
        adrs.append(f"{title}  [{status}]")
    s["adrs"] = adrs

    # Agent registry: name -> one-line scope
    agents = []
    reg = ROOT / "src" / "agents" / "AGENT_REGISTRY.yaml"
    if reg.exists():
        cur = None
        for line in reg.read_text(errors="ignore").splitlines():
            m = re.match(r"^\s{2}-\s+name:\s*(\S+)", line)
            if m:
                cur = m.group(1)
            elif cur and re.match(r"^\s+single_task:\s*(.+)", line):
                agents.append(f"{cur}: {re.match(r'^\s+single_task:\s*(.+)', line).group(1).strip(chr(34))}")
                cur = None
    s["agents"] = agents

    # Latest eval summary
    ev = sorted((ROOT / "eval_output").glob("**/summary.json"))
    s["eval"] = "no eval run yet"
    if ev:
        try:
            d = json.loads(ev[-1].read_text())
            s["eval"] = (f"{ev[-1].parent.name}: pass {d.get('passed','?')}/{d.get('total','?')} "
                         f"({d.get('pass_rate','?')}), p50 {d.get('latency_p50_ms','?')}ms, "
                         f"drift vs baseline {d.get('drift','n/a')}")
        except Exception:
            s["eval"] = f"{ev[-1]} (unparsed)"

    # Open HITL / gating flags left in code
    s["flags"] = [l for l in sh(
        "grep -rn --include=*.py --include=*.yaml --include=*.sql "
        "-E 'HITL|NEEDS_HUMAN|INDETERMINATE|TODO\\(gate\\)' . | head -12"
    ).splitlines() if l]
    return s


def render(n, s):
    return f"""================================================================================
PRESENTATION + SYSTEM DESIGN PROMPT  —  auto-generated, do not hand-edit
Regenerates every {EVERY} turns.  Last write: turn {n}  |  {s['ts']}
Source of truth: this repo.  Force refresh: `make deck`
================================================================================

ROLE
You are preparing a 10-minute readout of a multi-agent system built in a 2.5-hour
sprint. Audience: technical interviewers who will probe design tradeoffs, not
feature counts. Optimize for defensibility over completeness.

--------------------------------------------------------------------------------
STATE SNAPSHOT (scraped from repo at turn {n})
--------------------------------------------------------------------------------
Branch: {s['branch']}

Architecture decisions on record:
{bullets(s['adrs'])}

Agents shipped (narrow-scope, one job each):
{bullets(s['agents'])}

Latest eval:
  - {s['eval']}

Recent commits:
{bullets(s['commits'])}

Uncommitted work in flight:
{bullets(s['changed'], "  (clean tree)")}

Open human-review / gating flags:
{bullets(s['flags'], "  (no open flags)")}

--------------------------------------------------------------------------------
DECK TO PRODUCE (8 slides, in this order)
--------------------------------------------------------------------------------
1. PROBLEM FRAME — the problem in one sentence, plus the two constraints that
   actually shaped the build. Name what you deliberately did NOT build.
2. SYSTEM DESIGN — one diagram. Orchestrator(s), narrow sub-agents, the data
   plane, and the gate. Show the trust boundary, not just the boxes.
3. WHY NARROW AGENTS — contrast one broad agent vs. the decomposition here.
   Argue from testability, blast radius, and eval granularity — not from taste.
4. DATA LAYER — canonical entity model, the join keys, and which ISO tables
   normalize which fields. Explain what breaks without canonicalization.
5. GUARDRAILS — gating on sensitive/indeterminate input, retry policy and the
   fail-loud notification, least-privilege data scoping per agent, and the
   heuristic-override layer with its audit trail.
6. EVALS — the golden set: how it was built, what each tier measures, current
   numbers, and how drift is tracked across runs.
7. WHAT I'D DO WITH ANOTHER WEEK — ranked, with the reason each item is next.
8. RISKS + OPEN QUESTIONS — including anything still flagged for human review.

--------------------------------------------------------------------------------
RULES FOR THE GENERATED DECK
--------------------------------------------------------------------------------
- Every claim traces to a file in this repo. No aspirational features.
- If a number is not in eval_output/, say "not measured" — never estimate.
- Name the tradeoff you lost, not only the one you won.
- Keep speaker notes to 3 lines per slide.
- If state above is thin, say the sprint was timeboxed and show the seams.

--------------------------------------------------------------------------------
HOW TO USE
--------------------------------------------------------------------------------
Paste this whole file into Gamma (generate), or into Claude with:
  "Build the deck described in this prompt using only the state snapshot above."
================================================================================
"""


def main():
    n = bump()
    if n % EVERY != 0 and "--force" not in sys.argv:
        print(f"[turn {n}] deck prompt refreshes at turn {(n // EVERY + 1) * EVERY}")
        return
    try:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(render(n, collect()))
        print(f"[turn {n}] REFRESHED {OUT.relative_to(ROOT)} from live repo state.")
    except Exception as e:
        print(f"[turn {n}] deck prompt refresh failed (non-blocking): {e}")


if __name__ == "__main__":
    main()
    sys.exit(0)
