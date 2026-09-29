"""report — aggregate everything into a summary and export report.json + report.csv."""

from __future__ import annotations

import csv
import json
import os
from datetime import date

from ..contracts import RunMeta
from .. import schemas
from ._base import log, run


def handler(payload: dict, meta: RunMeta) -> dict:
    forecast = payload["forecast"]
    advice = payload["advice"]
    alerts = payload["alerts"]
    as_of = payload["as_of"]

    top_overages = [c["category"] for c in forecast["categories"] if c["projected_over_budget"]]
    num_over = len(top_overages)
    period_title = (forecast["period_label"] if forecast["period"] == "yearly"
                    else date.fromisoformat(as_of).strftime('%B %Y'))

    headline = (
        f"{period_title}: "
        f"projected savings ${forecast['projected_period_end_savings']:.0f}, "
        f"{len(alerts)} alert(s)"
        + (f", {num_over} categor{'y' if num_over == 1 else 'ies'} over budget" if num_over else "")
        + "."
    )

    report = {
        "as_of": as_of,
        "period": forecast["period"],
        "period_label": forecast["period_label"],
        "period_start": forecast["period_start"],
        "period_end": forecast["period_end"],
        "month": forecast["month"],
        "headline": headline,
        "num_transactions": len(payload["transactions"]),
        "num_alerts": len(alerts),
        "total_actual_spend": forecast["total_actual_spend"],
        "total_projected_spend": forecast["total_projected_spend"],
        "projected_month_end_savings": forecast["projected_month_end_savings"],
        "projected_period_end_savings": forecast["projected_period_end_savings"],
        "on_track_for_goal": advice["on_track_for_goal"],
        "top_overages": top_overages,
    }

    # Validate the Report before touching the filesystem, so we never write a
    # half-formed file on bad input.
    schemas.Report(**report)

    result = {**payload, "report": report}

    os.makedirs(meta.output_dir, exist_ok=True)
    json_path = os.path.join(meta.output_dir, "report.json")
    csv_path = os.path.join(meta.output_dir, "report.csv")

    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)

    def _pct(ratio) -> str:
        return f"{ratio * 100:.1f}%" if ratio != "" else ""

    with open(csv_path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        period_columns = [forecast["period"], forecast["period_label"],
                          forecast["period_start"], forecast["period_end"], as_of]
        writer.writerow(
            ["category", "budget", "actual_spend", "projected_spend",
             "is_fixed", "pct_of_budget", "projected_over_budget",
             "period", "period_label", "period_start", "period_end", "as_of"]
        )
        for c in forecast["categories"]:
            writer.writerow(
                [c["category"], c["budget"], c["actual_spend"], c["projected_spend"],
                 c["is_fixed"], _pct(c["pct_of_budget"]), c["projected_over_budget"]] + period_columns
            )

        total_budget = round(sum(c["budget"] for c in forecast["categories"]), 2)
        total_pct = round(forecast["total_projected_spend"] / total_budget, 4) if total_budget else 0.0
        writer.writerow(
            ["TOTAL", total_budget, forecast["total_actual_spend"],
             forecast["total_projected_spend"], "",
             _pct(total_pct), forecast["total_projected_spend"] > total_budget] + period_columns
        )

        # Income row uses the selected period's expected income.
        expected_income = forecast["period_income"]
        income_pct = round(forecast["income_so_far"] / expected_income, 4) if expected_income else 0.0
        writer.writerow(
            ["INCOME", expected_income, forecast["income_so_far"],
             expected_income, "", _pct(income_pct), ""] + period_columns
        )

        # Net row: income minus spend (budget=budgeted net, actual=net so far,
        # projected=projected period-end savings).
        net_budget = round(expected_income - total_budget, 2)
        net_actual = round(forecast["income_so_far"] - forecast["total_actual_spend"], 2)
        writer.writerow(
            ["NET", net_budget, net_actual,
             forecast["projected_period_end_savings"], "", "", ""] + period_columns
        )

    log(f"wrote {json_path} and {csv_path}")
    return result


if __name__ == "__main__":
    run("report", handler)
