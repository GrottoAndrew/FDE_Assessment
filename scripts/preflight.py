#!/usr/bin/env python3
"""
preflight.py — run this the morning of the sprint. `make preflight`

Every check here exists because its failure would cost sprint minutes at the
worst possible moment. Exits non-zero if anything blocking is broken.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OK, WARN, FAIL = "  ok  ", " warn ", " FAIL "
results: list[tuple[str, str, str]] = []


def record(status: str, name: str, detail: str = "") -> None:
    results.append((status, name, detail))
    print(f"[{status}] {name}" + (f"\n         {detail}" if detail else ""))


def env(key: str) -> str:
    f = ROOT / ".env"
    if not f.exists():
        return ""
    for line in f.read_text().splitlines():
        if line.startswith(f"{key}=") and not line.startswith("#"):
            return line.split("=", 1)[1].strip()
    return ""


# Homebrew postgres is keg-only, so psql is not on PATH by default.
_PG = [p for p in Path("/opt/homebrew/opt").glob("postgresql@*/bin") if p.is_dir()]
_ENV = {**os.environ,
        "PATH": os.pathsep.join([*(str(p) for p in sorted(_PG, reverse=True)),
                                 os.environ.get("PATH", "")])}


def sh(cmd: str) -> tuple[int, str]:
    r = subprocess.run(cmd, cwd=ROOT, shell=True, capture_output=True,
                       text=True, env=_ENV)
    return r.returncode, (r.stdout + r.stderr).strip()


# --- 1. secrets are not committable ----------------------------------------
def check_secrets() -> None:
    if not (ROOT / ".env").exists():
        record(FAIL, ".env exists", "copy .env.example -> .env and fill it in")
        return
    code, _ = sh("git check-ignore -q .env")
    record(OK if code == 0 else FAIL, ".env is gitignored",
           "" if code == 0 else "CRITICAL: .env would be committed")
    code, out = sh("python3 scripts/guard_secrets.py")
    record(OK if "SECRET GUARD" not in out else FAIL, "no secrets in committable files", out[:200])


# --- 2. the model key actually works ---------------------------------------
def check_anthropic() -> None:
    key = env("ANTHROPIC_API_KEY")
    if not key:
        record(FAIL, "ANTHROPIC_API_KEY set", "empty in .env")
        return
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01",
               "content-type": "application/json"}
    if ws := env("ANTHROPIC_WORKSPACE_ID"):
        headers["anthropic-workspace-id"] = ws
    body = json.dumps({"model": "claude-sonnet-5",
                       "messages": [{"role": "user", "content": "hi"}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages/count_tokens",
                                 data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20):
            record(OK, "Anthropic key works",
                   f"workspace: {ws}" if ws else "workspace-scoped key")
    except urllib.error.HTTPError as e:
        err = json.loads(e.read().decode() or "{}").get("error", {})
        msg = err.get("message", "")
        if "not scoped to a workspace" in msg:
            record(FAIL, "Anthropic key works",
                   "org-level key with no ANTHROPIC_WORKSPACE_ID. Either create a "
                   "workspace-scoped key in the Console, or set ANTHROPIC_WORKSPACE_ID "
                   "(wrkspc_...) in .env.")
        elif e.code == 401:
            record(FAIL, "Anthropic key works", "401 — key is invalid or revoked")
        else:
            record(FAIL, "Anthropic key works", f"HTTP {e.code}: {msg[:120]}")
    except Exception as e:
        record(WARN, "Anthropic key works", f"could not reach API: {type(e).__name__}")


# --- 3. database ------------------------------------------------------------
def check_db() -> None:
    url = env("DATABASE_URL")
    if not url or "user:pass@host" in url:
        record(WARN, "DATABASE_URL set", "still the placeholder — schema cannot be applied")
        return
    code, out = sh(f'psql "{url}" -tAc "select count(*) from iso.currency;"')
    if code != 0:
        record(FAIL, "database reachable", out[:160])
    elif out.strip() == "9":
        record(OK, "schema applied", "iso.currency has 9 rows")
    else:
        record(WARN, "schema applied", f"iso.currency returned {out.strip()!r}, expected 9")


# --- 4. the repo itself -----------------------------------------------------
def check_repo() -> None:
    code, out = sh(".venv/bin/pytest -q tests/ 2>&1 | tail -1")
    record(OK if code == 0 else FAIL, "contract tests", out[:120])
    code, out = sh(".venv/bin/python eval_workflows/run_evals.py --tier smoke 2>&1 | tail -2")
    record(OK if code in (0, 1) else FAIL, "eval harness runs", out.splitlines()[-1][:120] if out else "")
    code, out = sh("git status --porcelain")
    record(OK if not out else WARN, "working tree clean",
           "" if not out else f"{len(out.splitlines())} uncommitted file(s)")
    code, out = sh("gh api user --jq .login")
    record(OK if code == 0 else FAIL, "GitHub reachable",
           f"as {out}" if code == 0 else "run: gh auth refresh -h github.com")
    code, _ = sh("test -f .mcp.json")
    record(OK if code == 0 else WARN, "project MCP config present",
           "" if code == 0 else "no .mcp.json")
    p = ROOT / "docs/presentation/PRESENTATION_PROMPT.txt"
    record(OK if p.exists() else FAIL, "deck prompt exists",
           "" if p.exists() else "run: make deck")


def main() -> int:
    print("\npreflight — FDE_Assessment\n" + "=" * 52)
    for section, fn in (("secrets", check_secrets), ("model", check_anthropic),
                        ("database", check_db), ("repo", check_repo)):
        print(f"\n{section}")
        fn()
    fails = [r for r in results if r[0] == FAIL]
    warns = [r for r in results if r[0] == WARN]
    print("\n" + "=" * 52)
    print(f"{len(results) - len(fails) - len(warns)} ok, {len(warns)} warn, {len(fails)} FAIL")
    if fails:
        print("\nBlocking:")
        for _, name, detail in fails:
            print(f"  - {name}: {detail}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
