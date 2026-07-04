"""advice — savings-goal and allocation advice from mock market data (LLM optional)."""

from __future__ import annotations

from collections import defaultdict

from ..contracts import RunMeta
from .. import llm
from ._base import load_json, load_yaml, log, run

# Simple, static target allocation (a real product would personalize this).
_TARGET_ALLOCATION = {"equity": 60.0, "bond": 25.0, "cash": 10.0, "crypto": 5.0}
_REBALANCE_TOLERANCE_PCT = 5.0


def _portfolio(market: dict):
    prices = {a["symbol"]: a for a in market.get("assets", [])}
    by_class = defaultdict(float)
    total = 0.0
    for h in market.get("holdings", []):
        asset = prices.get(h["symbol"])
        if not asset:
            continue
        value = float(h["shares"]) * float(asset["price"])
        by_class[asset.get("asset_class", "other")] += value
        total += value
    return total, by_class


def handler(payload: dict, meta: RunMeta) -> dict:
    market = load_json(meta.market_path)
    budget_cfg = load_yaml(meta.budget_path)
    savings_cfg = budget_cfg.get("savings", {}) or {}

    forecast = payload["forecast"]
    savings_goal = round(float(savings_cfg.get("monthly_goal", 0.0)), 2)
    projected_savings = float(forecast["projected_month_end_savings"])
    on_track = projected_savings >= savings_goal

    ef_target = round(float(savings_cfg.get("emergency_fund_target", 0.0)), 2)
    current_savings = float(savings_cfg.get("current_savings", 0.0))
    ef_progress = round((current_savings / ef_target * 100.0) if ef_target > 0 else 0.0, 1)

    total_value, by_class = _portfolio(market)

    allocation = []
    for asset_class, target_pct in _TARGET_ALLOCATION.items():
        current_pct = round((by_class.get(asset_class, 0.0) / total_value * 100.0) if total_value > 0 else 0.0, 1)
        drift = current_pct - target_pct
        if abs(drift) <= _REBALANCE_TOLERANCE_PCT:
            action = "hold"
        else:
            action = "decrease" if drift > 0 else "increase"
        allocation.append(
            {
                "asset_class": asset_class,
                "current_pct": current_pct,
                "target_pct": target_pct,
                "action": action,
            }
        )

    # Deterministic recommendations.
    recs = []
    over = [c for c in forecast["categories"] if c["projected_over_budget"]]
    for c in sorted(over, key=lambda x: x["projected_spend"] - x["budget"], reverse=True)[:3]:
        recs.append(
            f"Trim {c['category']}: projected ${c['projected_spend']:.0f} vs "
            f"${c['budget']:.0f} budget this month."
        )
    if not on_track:
        gap = savings_goal - projected_savings
        recs.append(
            f"Projected savings ${projected_savings:.0f} is ${gap:.0f} short of your "
            f"${savings_goal:.0f} monthly goal — close it by curbing the categories above."
        )
    else:
        recs.append(
            f"On track: projected savings ${projected_savings:.0f} meets your "
            f"${savings_goal:.0f} goal. Automate the surplus into investments."
        )
    for a in allocation:
        if a["action"] != "hold":
            recs.append(
                f"Rebalance {a['asset_class']}: {a['current_pct']:.0f}% vs "
                f"{a['target_pct']:.0f}% target - {a['action']}."
            )
    if ef_target > 0 and ef_progress < 100:
        recs.append(
            f"Emergency fund at {ef_progress:.0f}% of your ${ef_target:.0f} target; "
            f"keep building the cash buffer."
        )

    # Optional LLM: replace the recommendation text with a nicer set (schema-guarded).
    if llm.llm_enabled(meta):
        context = {
            "projected_savings": projected_savings,
            "savings_goal": savings_goal,
            "on_track": on_track,
            "over_budget": [c["category"] for c in over],
            "allocation": allocation,
            "emergency_fund_progress_pct": ef_progress,
        }
        llm_recs = llm.advice_recommendations(context)
        if llm_recs:
            recs = llm_recs

    suggested = round(max(0.0, min(projected_savings, savings_goal)), 2) if projected_savings > 0 else 0.0

    advice = {
        "portfolio_value": round(total_value, 2),
        "savings_goal": savings_goal,
        "projected_savings": round(projected_savings, 2),
        "on_track_for_goal": on_track,
        "suggested_monthly_investment": suggested,
        "emergency_fund_target": ef_target,
        "emergency_fund_progress_pct": ef_progress,
        "allocation": allocation,
        "recommendations": recs,
    }

    log(f"advice: portfolio ${advice['portfolio_value']:.2f}, on_track={on_track}, {len(recs)} recs")
    return {**payload, "advice": advice}


if __name__ == "__main__":
    run("advice", handler)
