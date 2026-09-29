"""Regression coverage for calendar filtering and monthly/yearly reports."""

import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path

from main import _parse_args, _print_summary
from finance_agent.agents import advice, alerts, forecast, ingest, report
from finance_agent.contracts import RunMeta
from finance_agent.guards import BoundaryValidationError, validate_payload
from finance_agent.schemas import ReportOutput


class PeriodTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.csv = self.root / "transactions.csv"
        self.csv.write_text(
            "date,description,amount\n"
            "2023-12-31,groceries,-9999\n"
            "2024-01-01,housing,-1000\n"
            "2024-01-31,groceries,-310\n"
            "2024-01-31,income,3000\n"
            "2024-02-01,housing,-1000\n"
            "2024-02-15,groceries,-150\n"
            "2024-02-15,income,1500\n"
            "2024-03-01,groceries,-9999\n", encoding="utf-8"
        )
        (self.root / "budget.yaml").write_text(
            "monthly_income: 3000\nbudgets:\n  housing: 1000\n  groceries: 300\n"
            "fixed_categories: [housing]\nsavings:\n  monthly_goal: 500\n"
            "  emergency_fund_target: 10000\n  current_savings: 2000\n",
            encoding="utf-8",
        )
        (self.root / "market.json").write_text("{}", encoding="utf-8")

    def meta(self, period="monthly", as_of=date(2024, 2, 15)):
        return RunMeta(
            csv_path=str(self.csv), budget_path=str(self.root / "budget.yaml"),
            categories_path="unused", market_path=str(self.root / "market.json"),
            output_dir=str(self.root / "out"), period=period, as_of=as_of,
        )

    def categorized(self, meta):
        payload = ingest.handler({}, meta)
        for tx in payload["transactions"]:
            tx["category"] = tx["description"]
            tx["is_income"] = tx["amount"] > 0
        return payload

    def run_report(self, meta):
        payload = self.categorized(meta)
        for handler in (forecast.handler, advice.handler, alerts.handler, report.handler):
            payload = handler(payload, meta)
        return validate_payload(ReportOutput, payload)

    def test_monthly_filters_previous_month_year_and_future(self):
        result = self.run_report(self.meta())
        f = result["forecast"]
        self.assertEqual(len(result["transactions"]), 3)
        self.assertEqual(f["total_actual_spend"], 1150)
        self.assertEqual(f["income_so_far"], 1500)
        self.assertEqual(f["total_projected_spend"], 1290)
        self.assertEqual(f["days_in_period"], 29)
        self.assertEqual(f["days_elapsed"], 15)
        self.assertEqual(f["projected_month_end_savings"], 1710)
        self.assertEqual(result["advice"]["savings_goal"], 500)

    def test_yearly_scales_budgets_income_goals_and_recurring_costs(self):
        result = self.run_report(self.meta("yearly"))
        f = result["forecast"]
        self.assertEqual(len(result["transactions"]), 6)
        self.assertEqual(f["total_actual_spend"], 2460)
        self.assertEqual(f["income_so_far"], 4500)
        self.assertEqual(f["days_elapsed"], 46)
        self.assertEqual(f["days_in_period"], 366)
        self.assertEqual(f["total_projected_spend"], 15660)
        self.assertEqual(f["period_income"], 36000)
        self.assertEqual(f["projected_period_end_savings"], 20340)
        categories = {c["category"]: c for c in f["categories"]}
        self.assertEqual(categories["housing"]["projected_spend"], 12000)
        self.assertEqual(categories["groceries"]["budget"], 3600)
        self.assertTrue(categories["groceries"]["projected_over_budget"])
        self.assertEqual(result["advice"]["savings_goal"], 6000)
        self.assertEqual(result["advice"]["suggested_monthly_investment"], 500)
        self.assertEqual(result["advice"]["suggested_period_investment"], 6000)
        self.assertEqual(result["advice"]["emergency_fund_target"], 10000)
        self.assertIsNone(f["projected_month_end_savings"])
        self.assertTrue(any(a["kind"] == "budget_overage" for a in result["alerts"]))
        self.assertTrue(result["report"]["headline"].startswith("2024:"))
        self.assertNotIn("this month", " ".join(result["advice"]["recommendations"]))

    def test_exports_and_console_identify_both_periods(self):
        for period in ("monthly", "yearly"):
            with self.subTest(period=period):
                result = self.run_report(self.meta(period))
                saved = json.loads((self.root / "out/report.json").read_text())
                self.assertEqual(saved["report"]["period"], period)
                with (self.root / "out/report.csv").open(newline="") as fh:
                    rows = list(csv.DictReader(fh))
                self.assertTrue(all(r["period"] == period for r in rows))
                self.assertEqual(float(rows[-2]["budget"]), result["forecast"]["period_income"])
                self.assertEqual(float(rows[-1]["projected_spend"]),
                                 result["forecast"]["projected_period_end_savings"])
                output = io.StringIO()
                with redirect_stdout(output):
                    _print_summary(result)
                self.assertIn(f"{period.upper()} BUDGET FORECAST", output.getvalue())

    def test_completed_period_projects_actual_spend(self):
        for period, cutoff in (("monthly", date(2024, 2, 29)),
                               ("yearly", date(2024, 12, 31)),
                               ("yearly", date(2023, 12, 31))):
            with self.subTest(period=period, cutoff=cutoff):
                meta = self.meta(period, cutoff)
                f = forecast.handler(self.categorized(meta), meta)["forecast"]
                self.assertEqual(f["total_projected_spend"], f["total_actual_spend"])
                self.assertEqual(f["days_elapsed"], f["days_in_period"])

    def test_default_uses_latest_csv_month(self):
        payload = ingest.handler({}, self.meta(as_of=None))
        self.assertEqual(payload["as_of"], "2024-03-01")
        self.assertEqual(len(payload["transactions"]), 1)

    def test_empty_selected_period_fails(self):
        with self.assertRaisesRegex(BoundaryValidationError, "no transactions in selected period"):
            ingest.handler({}, self.meta(as_of=date(2025, 1, 1)))

    def test_cli_defaults_and_date_selection(self):
        self.assertEqual(_parse_args([]).period, "monthly")
        args = _parse_args(["--period", "yearly", "--as-of", "2024-12-31"])
        self.assertEqual(args.period, "yearly")
        self.assertEqual(args.as_of, date(2024, 12, 31))
        for args in (["--period", "weekly"], ["--as-of", "2024-02-30"]):
            with self.assertRaises(SystemExit):
                _parse_args(args)


if __name__ == "__main__":
    unittest.main()
