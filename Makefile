.PHONY: help setup test tdd eval evalq golden schema seed lint deck clean

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup:   ## create venv + install
	python3 -m venv .venv && .venv/bin/pip install -q -U pip pytest pyyaml jsonschema

test:    ## run the full test suite (contracts first)
	.venv/bin/pytest -q tests/

tdd:     ## watch-mode-ish: run only contract tests, fail fast
	.venv/bin/pytest -x -q tests/test_contracts.py

schema:  ## print the DDL that must be applied before anything runs
	@cat src/data/schema/*.sql

seed:    ## generate synthetic data into src/data/synthetic/
	.venv/bin/python scripts/gen_synthetic.py

eval:    ## run the full golden-set eval, write to eval_output/
	.venv/bin/python eval_workflows/run_evals.py --golden $(or $(GOLDEN),eval_workflows/golden/golden_set.jsonl)

evalq:   ## quick smoke eval (tier=smoke only)
	.venv/bin/python eval_workflows/run_evals.py --tier smoke

deck:    ## regenerate the presentation prompt now (normally every 5th turn)
	python3 scripts/turn_tick.py --force

clean:
	rm -rf .venv .pytest_cache __pycache__ eval_output/*/raw
