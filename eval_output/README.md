# eval_output/

Written by `make eval`. One directory per run: `<UTC timestamp>-<short id>/`

| file | what it is |
|---|---|
| `summary.json` | headline numbers, per-category breakdown, drift verdict. Scraped by `scripts/turn_tick.py` into the deck prompt. |
| `results.jsonl` | one row per golden case: expected, actual, pass/fail, latency, and *why the case exists*. |
| `report.md` | the human-readable version. Read this one. |

`baseline/` holds the reference run. Drift is computed **per case**, not just on
the aggregate — a run that stays at 23/26 while swapping which three fail is a
regression, and an aggregate-only comparison would call it stable.

Set a baseline once the system is real:

    python3 eval_workflows/run_evals.py --set-baseline

Runs carry `adapter_mode`. A run with `adapter_mode: stub` describes the harness,
not the system — never quote its numbers in the readout.
