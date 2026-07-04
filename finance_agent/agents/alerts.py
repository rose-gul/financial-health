"""alerts — raise budget-overage, budget-warning, market-move, and savings alerts."""

from __future__ import annotations

from ..contracts import RunMeta
from ._base import load_json, load_yaml, log, run


def handler(payload: dict, meta: RunMeta) -> dict:
    cfg = load_yaml(meta.budget_path)
    thresholds = cfg.get("alerts", {}) or {}
    overage_ratio = float(thresholds.get("budget_overage_ratio", 1.0))
    warning_ratio = float(thresholds.get("budget_warning_ratio", 0.85))
    market_move_pct = float(thresholds.get("market_move_pct", 4.0))

    market = load_json(meta.market_path)
    forecast = payload["forecast"]
    advice = payload["advice"]

    alerts = []

    # Budget alerts (projected overage takes precedence over an early warning).
    for c in forecast["categories"]:
        budget = c["budget"]
        if budget <= 0:
            continue
        projected_ratio = c["projected_spend"] / budget
        actual_ratio = c["actual_spend"] / budget
        if projected_ratio >= overage_ratio and c["projected_over_budget"]:
            alerts.append(
                {
                    "id": f"budget_overage:{c['category']}",
                    "severity": "critical",
                    "kind": "budget_overage",
                    "title": f"{c['category'].title()} projected over budget",
                    "message": (
                        f"Projected ${c['projected_spend']:.0f} vs ${budget:.0f} budget "
                        f"({projected_ratio * 100:.0f}% of budget)."
                    ),
                    "category": c["category"],
                    "value": round(projected_ratio, 3),
                }
            )
        elif actual_ratio >= warning_ratio:
            alerts.append(
                {
                    "id": f"budget_warning:{c['category']}",
                    "severity": "warning",
                    "kind": "budget_warning",
                    "title": f"{c['category'].title()} nearing budget",
                    "message": (
                        f"Already spent ${c['actual_spend']:.0f} of ${budget:.0f} "
                        f"({actual_ratio * 100:.0f}%)."
                    ),
                    "category": c["category"],
                    "value": round(actual_ratio, 3),
                }
            )

    # Market-move alerts.
    for asset in market.get("assets", []):
        change = float(asset.get("daily_change_pct", 0.0))
        if abs(change) >= market_move_pct:
            direction = "surged" if change > 0 else "dropped"
            alerts.append(
                {
                    "id": f"market_move:{asset['symbol']}",
                    "severity": "warning",
                    "kind": "market_move",
                    "title": f"{asset['symbol']} {direction} {abs(change):.1f}%",
                    "message": (
                        f"{asset.get('name', asset['symbol'])} {direction} {change:+.1f}% "
                        f"today to ${asset['price']:.2f}."
                    ),
                    "symbol": asset["symbol"],
                    "value": change,
                }
            )

    # Savings shortfall.
    if not advice["on_track_for_goal"]:
        gap = advice["savings_goal"] - advice["projected_savings"]
        alerts.append(
            {
                "id": "savings_shortfall",
                "severity": "warning",
                "kind": "savings_shortfall",
                "title": "Savings goal at risk",
                "message": (
                    f"Projected savings ${advice['projected_savings']:.0f} is "
                    f"${gap:.0f} below your ${advice['savings_goal']:.0f} goal."
                ),
                "value": round(gap, 2),
            }
        )

    log(f"alerts: {len(alerts)} raised")
    return {**payload, "alerts": alerts}


if __name__ == "__main__":
    run("alerts", handler)
