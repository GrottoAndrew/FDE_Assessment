.PHONY: help setup test tdd eval evalq golden schema seed lint deck preflight cost poll pollplan dbreport seed-nvda clean

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

cost:    ## model routing cost model + ROI sensitivity
	python3 scripts/cost_model.py --volume $(or $(VOL),5000)

preflight: ## run the morning-of checks — do this BEFORE the sprint
	.venv/bin/python scripts/preflight.py

setup:   ## create venv + install
	python3 -m venv .venv && .venv/bin/pip install -q -U pip -r requirements.txt

test:    ## run the full test suite (contracts first)
	.venv/bin/pytest -q tests/

tdd:     ## watch-mode-ish: run only contract tests, fail fast
	.venv/bin/pytest -x -q tests/test_contracts.py

schema:  ## print the DDL that must be applied before anything runs
	@cat src/data/schema/*.sql

seed:    ## load the demonstration slice (alias for seed-nvda; gen_synthetic.py was never written)
	$(MAKE) seed-nvda

eval:    ## run the full golden-set eval, write to eval_output/
	.venv/bin/python eval_workflows/run_evals.py --golden $(or $(GOLDEN),eval_workflows/golden/golden_set.jsonl)

evalq:   ## quick smoke eval (tier=smoke only)
	.venv/bin/python eval_workflows/run_evals.py --tier smoke

deck:    ## regenerate the presentation prompt now (normally every 5th turn)
	python3 scripts/turn_tick.py --force

dbreport: ## structural analysis of the live local instance
	psql "$(or $(DATABASE_URL),postgresql:///fde)" -f scripts/db_report.sql

seed-nvda: ## load the NVDA demonstration slice (entity, security, synonyms)
	psql "$(or $(DATABASE_URL),postgresql:///fde)" -v ON_ERROR_STOP=1 -f src/data/synthetic/nvda_slice.sql

# 20, not 15: a 15-minute schedule is 567 calls/month against a 500 cap and
# --once refuses to start on it, so `make poll` was a dead target (RT-09).
pollplan: ## budget arithmetic for the NVDA schedule — no network
	.venv/bin/python scripts/poll_nvda.py --plan --interval $(or $(IV),20) --cap $(or $(CAP),500)

poll:    ## one NVDA poll cycle (EDGAR + delayed price), recording golden fixtures
	.venv/bin/python scripts/poll_nvda.py --once --record --interval $(or $(IV),20) --cap $(or $(CAP),500)

clean:
	rm -rf .venv .pytest_cache __pycache__ eval_output/*/raw
