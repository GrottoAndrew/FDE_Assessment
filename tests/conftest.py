import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def root() -> Path:
    return ROOT


@pytest.fixture(scope="session")
def registry() -> dict:
    return yaml.safe_load((ROOT / "src/agents/AGENT_REGISTRY.yaml").read_text())


@pytest.fixture(scope="session")
def gating() -> dict:
    return yaml.safe_load((ROOT / "src/policies/gating.yaml").read_text())


@pytest.fixture(scope="session")
def heuristics() -> dict:
    return yaml.safe_load((ROOT / "src/policies/heuristics.yaml").read_text())


@pytest.fixture(scope="session")
def retry() -> dict:
    return yaml.safe_load((ROOT / "src/policies/retry.yaml").read_text())


@pytest.fixture(scope="session")
def golden() -> list[dict]:
    import json
    p = ROOT / "eval_workflows/golden/golden_set.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
