#!/usr/bin/env python3
"""
cost_model.py — model-routing cost math for the ROI slide.

Prices verified against platform.claude.com/docs/en/about-claude/pricing on
2026-09-08. Sonnet 5 is $2/$10 (the launch "introductory" price became standard).

    python3 scripts/cost_model.py               # routing table + ROI
    python3 scripts/cost_model.py --json        # machine-readable
    python3 scripts/cost_model.py --volume 5000 # tasks/month
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

# $ per 1M tokens: (input, output, cache_write_5m, cache_read)
PRICES = {
    "claude-haiku-4-5": (1.00, 5.00, 1.25, 0.10),
    "claude-sonnet-5":  (2.00, 10.00, 2.50, 0.20),
    "claude-opus-5":    (5.00, 25.00, 6.25, 0.50),
    "claude-fable-5":   (10.00, 50.00, 12.50, 1.00),
}

# Routing and token profiles are READ FROM THE REGISTRY, not restated here.
# Two sources of truth drift, and a drifted ROI slide describes a system that
# does not exist (gap G-14). `model: none` agents are deterministic code paths
# and cost zero tokens by construction.
PRICES["none"] = (0.0, 0.0, 0.0, 0.0)

REGISTRY = Path(__file__).resolve().parent.parent / "src/agents/AGENT_REGISTRY.yaml"


def load_agents() -> list[tuple]:
    """(name, tier, model, tokens_in, tokens_out, share) straight from the registry."""
    import yaml
    reg = yaml.safe_load(REGISTRY.read_text())
    tier_of = {"none": 0, "claude-haiku-4-5": 1, "claude-sonnet-5": 2, "claude-opus-5": 3}
    out = []
    for node in list(reg["agents"]) + list(reg["orchestrators"]):
        model = node["model"]
        cp = node.get("cost_profile") or {"tokens_in": 5000, "tokens_out": 800, "share": 1.00}
        out.append((node["name"], tier_of.get(model, 3), model,
                    cp["tokens_in"], cp["tokens_out"], cp["share"]))
    return out


AGENTS = load_agents()

CACHE_HIT_RATE = 0.70   # system prompt + tool schemas + policy YAML are stable


def cost(model: str, tok_in: int, tok_out: int, cached: bool = True) -> float:
    p_in, p_out, _, p_read = PRICES[model]
    if cached:
        hit = tok_in * CACHE_HIT_RATE
        miss = tok_in - hit
        cin = (hit * p_read + miss * p_in) / 1e6
    else:
        cin = tok_in * p_in / 1e6
    return cin + tok_out * p_out / 1e6


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--volume", type=int, default=1000, help="tasks per month")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    rows = []
    for name, tier, model, ti, to, share in AGENTS:
        c_cached = cost(model, ti, to, True)
        c_raw = cost(model, ti, to, False)
        c_opus = cost("claude-opus-5", ti, to, True)   # if everything ran on Opus
        rows.append({
            "agent": name, "tier": tier, "model": model,
            "tokens_in": ti, "tokens_out": to, "share": share,
            "cost_per_call": round(c_cached, 6),
            "cost_per_call_uncached": round(c_raw, 6),
            "cost_per_1k_calls": round(c_cached * 1000, 3),
            "cost_if_all_opus": round(c_opus, 6),
        })

    per_task_routed = sum(r["cost_per_call"] * r["share"] for r in rows)
    per_task_allopus = sum(r["cost_if_all_opus"] * r["share"] for r in rows)
    per_task_nocache = sum(r["cost_per_call_uncached"] * r["share"] for r in rows)

    summary = {
        "cache_hit_rate": CACHE_HIT_RATE,
        "per_task_routed": round(per_task_routed, 5),
        "per_task_all_opus": round(per_task_allopus, 5),
        "per_task_routed_nocache": round(per_task_nocache, 5),
        "routing_savings_pct": round((1 - per_task_routed / per_task_allopus) * 100, 1),
        "caching_savings_pct": round((1 - per_task_routed / per_task_nocache) * 100, 1),
        "monthly_volume": a.volume,
        "monthly_routed": round(per_task_routed * a.volume, 2),
        "monthly_all_opus": round(per_task_allopus * a.volume, 2),
        "monthly_saved": round((per_task_allopus - per_task_routed) * a.volume, 2),
    }

    if a.json:
        print(json.dumps({"prices": PRICES, "agents": rows, "summary": summary}, indent=2))
        return

    print("\nMODEL PRICING ($ per 1M tokens, verified 2026-09-08)")
    print(f"{'model':<20}{'input':>9}{'output':>9}{'cache wr':>10}{'cache rd':>10}")
    print("-" * 58)
    for m, (i, o, w, r) in PRICES.items():
        print(f"{m:<20}{i:>9.2f}{o:>9.2f}{w:>10.2f}{r:>10.2f}")

    print(f"\nPER 100K TOKENS  (input / output)")
    for m, (i, o, _, _) in PRICES.items():
        print(f"  {m:<20} ${i/10:>6.2f} in   ${o/10:>6.2f} out")

    print(f"\n\nROUTING TABLE — sales example, {CACHE_HIT_RATE:.0%} cache hit rate")
    print(f"{'agent':<28}{'T':>2} {'model':<18}{'in':>6}{'out':>6}{'$/call':>10}{'$/1k':>9}")
    print("-" * 79)
    for t in (1, 2, 3):
        for r in [x for x in rows if x["tier"] == t]:
            print(f"{r['agent']:<28}{r['tier']:>2} {r['model'].replace('claude-',''):<18}"
                  f"{r['tokens_in']:>6}{r['tokens_out']:>6}"
                  f"{r['cost_per_call']:>10.5f}{r['cost_per_1k_calls']:>9.2f}")
        print()

    s = summary
    print("COST OF ONE COMPLETE TASK (gate + orchestrator + weighted sub-agents)")
    print(f"  routed + cached      ${s['per_task_routed']:.5f}")
    print(f"  routed, no caching   ${s['per_task_routed_nocache']:.5f}"
          f"   ({s['caching_savings_pct']}% saved by caching)")
    print(f"  everything on Opus   ${s['per_task_all_opus']:.5f}"
          f"   ({s['routing_savings_pct']}% saved by routing)")
    print(f"\nAT {a.volume:,} TASKS/MONTH")
    print(f"  routed   ${s['monthly_routed']:>10,.2f}")
    print(f"  all-Opus ${s['monthly_all_opus']:>10,.2f}")
    print(f"  saved    ${s['monthly_saved']:>10,.2f}/mo  "
          f"(${s['monthly_saved']*12:,.2f}/yr)")
    sensitivity(a.volume)


def sensitivity(volume: int) -> None:
    """Where the money actually is. Run the same traffic under four configs."""
    configs = {
        "all-Opus (no routing, no cache)":
            {a[0]: "claude-opus-5" for a in AGENTS},
        "all-Opus + caching":
            {a[0]: "claude-opus-5" for a in AGENTS},
        "routed + caching (as designed)":
            {a[0]: a[2] for a in AGENTS},
        "routed + caching, orchestrator on Sonnet":
            {a[0]: ("claude-sonnet-5" if a[0].endswith("_orchestrator") else a[2])
             for a in AGENTS},
    }
    print("\n\nSENSITIVITY — same traffic, four configurations")
    print(f"{'configuration':<44}{'$/task':>10}{'$/mo':>12}{'vs base':>10}")
    print("-" * 76)
    base = None
    for i, (label, mapping) in enumerate(configs.items()):
        use_cache = i != 0
        total = sum(cost(mapping[n], ti, to, use_cache) * share
                    for n, _, _, ti, to, share in AGENTS)
        base = base or total
        print(f"{label:<44}{total:>10.5f}{total*volume:>12,.2f}"
              f"{(1-total/base)*100:>9.1f}%")
    print("\nRead this before quoting a savings number: most of the spend sits in the")
    print("two Opus agents that run on every task (orchestrator, red team). Routing the")
    print("leaf agents down is real but bounded. Caching the stable prefix beats it, and")
    print("moving the orchestrator is the single biggest lever - if quality allows.")


if __name__ == "__main__":
    main()
