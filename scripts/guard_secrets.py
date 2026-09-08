#!/usr/bin/env python3
"""
guard_secrets.py — PostToolUse hook on Write|Edit.

Blocks the sprint's most expensive unforced error: a live key committed into a
demo repo. Scans the working tree for high-signal secret shapes and prints a
warning back into context. Never exits non-zero (advisory, not blocking).
"""
import re
import subprocess
import sys
from pathlib import Path

PATTERNS = [
    ("Anthropic key", r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    ("OpenAI key", r"sk-[A-Za-z0-9]{32,}"),
    ("Supabase service role JWT", r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,}"),
    ("AWS access key", r"AKIA[0-9A-Z]{16}"),
    ("GitHub token", r"gh[pousr]_[A-Za-z0-9]{30,}"),
    ("Postgres URL with password", r"postgres(?:ql)?://[^:\s]+:[^@\s]{6,}@"),
]
SKIP = {".git", ".venv", "node_modules", "__pycache__", "eval_output", ".agents"}


def ignored(root: Path) -> set[str]:
    """Paths git already refuses to commit. A key in .env is correct, not a leak —
    the guard only cares about files that could actually reach the remote."""
    out = subprocess.run(
        "git ls-files --others --ignored --exclude-standard --directory",
        cwd=root, shell=True, capture_output=True, text=True).stdout
    return {line.rstrip("/") for line in out.splitlines() if line.strip()}


def main():
    root = Path(subprocess.run("git rev-parse --show-toplevel", shell=True,
                               capture_output=True, text=True).stdout.strip() or ".")
    skip_paths = ignored(root)
    hits = []
    for p in root.rglob("*"):
        if not p.is_file() or any(s in p.parts for s in SKIP):
            continue
        rel = str(p.relative_to(root))
        if rel in skip_paths or any(rel.startswith(d + "/") for d in skip_paths):
            continue
        if p.name in {".env.example", "guard_secrets.py"} or p.suffix in {".png", ".pdf", ".jpg"}:
            continue
        try:
            text = p.read_text(errors="ignore")
        except Exception:
            continue
        for label, pat in PATTERNS:
            if re.search(pat, text):
                hits.append(f"{p.relative_to(root)}: possible {label}")
    if hits:
        print("SECRET GUARD — do not commit until resolved:")
        for h in hits[:10]:
            print(f"  ! {h}")
        print("  Move the value to .env (gitignored) and reference it via os.environ.")

if __name__ == "__main__":
    main()
    sys.exit(0)
