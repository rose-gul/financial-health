"""forecast — project month-end spend per category and compare against the budget."""

from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date

from ..contracts import RunMeta
from ._base import load_yaml, log, run


def handler(payload: dict, meta: RunMeta) -> dict:
    cfg = load_yaml(meta.budget_path)
    budgets = {k: float(v) for k, v in (cfg.get("budgets", {}) or {}).items()}
    fixed = set(cfg.get("fixed_categories", []) or [])
    monthly_income = float(cfg.get("monthly_income", 0.0))

    as_of = date.fromisoformat(payload["as_of"])
    days_in_month = calendar.monthrange(as_of.year, as_of.month)[1]
    days_elapsed = as_of.day
    factor = days_in_month / days_elapsed  # linear month-end projection multiplier

    actual = defaultdict(float)
    income_so_far = 0.0
    for tx in payload["transactions"]:
        if tx.get("is_income"):
            income_so_far += tx["amount"]
            continue
        if tx["amount"] < 0:  # money out
            actual[tx["category"]] += -tx["amount"]

    categories = []
    total_actual = 0.0
    total_projected = 0.0
    for category in sorted(set(budgets) | set(actual)):
        spent = round(actual.get(category, 0.0), 2)
        budget = round(budgets.get(category, 0.0), 2)
        is_fixed = category in fixed
        projected = round(spent if is_fixed else spent * factor, 2)
        pct = round(projected / budget, 4) if budget > 0 else 0.0
        categories.append(
            {
                "category": category,
                "budget": budget,
                "actual_spend": spent,
                "projected_spend": projected,
                "is_fixed": is_fixed,
                "pct_of_budget": pct,
                "projected_over_budget": bool(budget > 0 and projected > budget),
            }
        )
        total_actual += spent
        total_projected += projected

    forecast = {
        "month": as_of.strftime("%Y-%m"),
        "days_elapsed": days_elapsed,
        "days_in_month": days_in_month,
        "monthly_income": round(monthly_income, 2),
        "income_so_far": round(income_so_far, 2),
        "total_actual_spend": round(total_actual, 2),
        "total_projected_spend": round(total_projected, 2),
        "projected_month_end_savings": round(monthly_income - total_projected, 2),
        "categories": categories,
    }

    log(
        f"forecast {forecast['month']}: day {days_elapsed}/{days_in_month}, "
        f"projected spend ${forecast['total_projected_spend']:.2f}, "
        f"projected savings ${forecast['projected_month_end_savings']:.2f}"
    )
    return {"as_of": payload["as_of"], "transactions": payload["transactions"], "forecast": forecast}


if __name__ == "__main__":
    run("forecast", handler)
