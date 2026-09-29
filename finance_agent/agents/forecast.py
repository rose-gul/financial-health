"""forecast — project month- or year-end spending against the matching budget."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from ..contracts import RunMeta
from ..periods import period_bounds
from ._base import load_yaml, log, run


def handler(payload: dict, meta: RunMeta) -> dict:
    cfg = load_yaml(meta.budget_path)
    budgets = {k: float(v) for k, v in (cfg.get("budgets", {}) or {}).items()}
    fixed = set(cfg.get("fixed_categories", []) or [])
    monthly_income = float(cfg.get("monthly_income", 0.0))

    as_of = date.fromisoformat(payload["as_of"])
    start, end = period_bounds(as_of, meta.period)
    yearly = meta.period == "yearly"
    months = 12 if yearly else 1
    days_in_period = (end - start).days + 1
    days_elapsed = (as_of - start).days + 1
    factor = days_in_period / days_elapsed
    # Fixed charges recur monthly; never extrapolate them by partial-month days.
    fixed_factor = 12 / as_of.month if yearly else 1
    transactions = [
        t for t in payload["transactions"]
        if start.isoformat() <= t["date"] <= as_of.isoformat()
    ]

    actual = defaultdict(float)
    income_so_far = 0.0
    for tx in transactions:
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
        budget = round(budgets.get(category, 0.0) * months, 2)
        is_fixed = category in fixed
        projected = round(spent * (fixed_factor if is_fixed else factor), 2)
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
        "period": meta.period,
        "period_label": as_of.strftime("%Y" if yearly else "%Y-%m"),
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "days_in_period": days_in_period,
        "period_income": round(monthly_income * months, 2),
        "projected_period_end_savings": round(monthly_income * months - total_projected, 2),
        "month": None if yearly else as_of.strftime("%Y-%m"),
        "days_elapsed": days_elapsed,
        "days_in_month": None if yearly else days_in_period,
        "monthly_income": round(monthly_income, 2),
        "income_so_far": round(income_so_far, 2),
        "total_actual_spend": round(total_actual, 2),
        "total_projected_spend": round(total_projected, 2),
        "projected_month_end_savings": None if yearly else round(monthly_income - total_projected, 2),
        "categories": categories,
    }

    log(
        f"forecast {forecast['period_label']}: day {days_elapsed}/{days_in_period}, "
        f"projected spend ${forecast['total_projected_spend']:.2f}, "
        f"projected savings ${forecast['projected_period_end_savings']:.2f}"
    )
    return {"as_of": payload["as_of"], "transactions": transactions, "forecast": forecast}


if __name__ == "__main__":
    run("forecast", handler)
