"""Finance Agent CLI.

Runs the isolated multi-agent pipeline over a transactions CSV and prints a summary,
writing outputs/report.json and outputs/report.csv.

    python main.py --input data/transactions.csv
    python main.py --input data/transactions.csv --llm     # opt-in Claude assist
"""

from __future__ import annotations

import argparse
import os
import sys

# Ensure the package is importable when run as `python main.py` from anywhere.
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
except Exception:  # noqa: BLE001 - dotenv is a convenience, not required
    pass

from finance_agent.contracts import RunMeta  # noqa: E402
from finance_agent.orchestrator import run_pipeline  # noqa: E402
from finance_agent.runner import StepError  # noqa: E402

_SEVERITY_MARK = {"critical": "[!!]", "warning": "[! ]", "info": "[  ]"}


def _abs(path: str) -> str:
    return path if os.path.isabs(path) else os.path.join(PROJECT_ROOT, path)


def _parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Multi-agent personal-finance pipeline.")
    p.add_argument("--input", default="data/transactions.csv", help="transactions CSV path")
    p.add_argument("--budget", default="config/budget.yaml", help="budget YAML path")
    p.add_argument("--categories", default="config/categories.yaml", help="categories YAML path")
    p.add_argument("--market", default="data/market.json", help="market data JSON path")
    p.add_argument("--output-dir", default="outputs", help="directory for report.json/report.csv")
    p.add_argument("--timeout", type=float, default=30.0, help="per-step timeout in seconds")
    p.add_argument("--llm", action="store_true", help="enable optional Claude assist")
    p.add_argument("--quiet", action="store_true", help="suppress per-step progress")
    return p.parse_args(argv)


def _print_summary(final: dict) -> None:
    report = final["report"]
    forecast = final["forecast"]
    advice = final["advice"]
    alerts = final["alerts"]

    line = "=" * 68
    print(line)
    print(report["headline"])
    print(line)

    print("\nBUDGET FORECAST  (day "
          f"{forecast['days_elapsed']}/{forecast['days_in_month']} of {forecast['month']})")
    print(f"  {'category':<14}{'actual':>10}{'projected':>12}{'budget':>10}   status")
    for c in forecast["categories"]:
        status = "OVER" if c["projected_over_budget"] else ("fixed" if c["is_fixed"] else "ok")
        print(f"  {c['category']:<14}{c['actual_spend']:>10.2f}"
              f"{c['projected_spend']:>12.2f}{c['budget']:>10.2f}   {status}")
    print(f"  {'-' * 60}")
    print(f"  {'TOTAL':<14}{forecast['total_actual_spend']:>10.2f}"
          f"{forecast['total_projected_spend']:>12.2f}")
    print(f"  Projected month-end savings: ${forecast['projected_month_end_savings']:.2f}"
          f"  (goal ${advice['savings_goal']:.0f}, "
          f"{'ON TRACK' if advice['on_track_for_goal'] else 'SHORT'})")

    print(f"\nPORTFOLIO  ${advice['portfolio_value']:.2f}")
    for a in advice["allocation"]:
        print(f"  {a['asset_class']:<8}{a['current_pct']:>6.1f}%  "
              f"target {a['target_pct']:>4.0f}%  -> {a['action']}")

    print(f"\nADVICE")
    for r in advice["recommendations"]:
        print(f"  - {r}")

    print(f"\nALERTS  ({len(alerts)})")
    if not alerts:
        print("  none")
    for al in sorted(alerts, key=lambda x: x["severity"] != "critical"):
        print(f"  {_SEVERITY_MARK.get(al['severity'], '[  ]')} {al['title']}: {al['message']}")

    print()


def main(argv=None) -> int:
    args = _parse_args(argv)
    meta = RunMeta(
        csv_path=_abs(args.input),
        budget_path=_abs(args.budget),
        categories_path=_abs(args.categories),
        market_path=_abs(args.market),
        output_dir=_abs(args.output_dir),
        llm_enabled=args.llm,
    )

    def log(message: str) -> None:
        if not args.quiet:
            print(message, file=sys.stderr)

    try:
        final = run_pipeline(meta, project_root=PROJECT_ROOT, timeout=args.timeout, log=log)
    except StepError as exc:
        print(f"\nPIPELINE FAILED at step '{exc.step}': {exc.reason}", file=sys.stderr)
        if exc.stderr:
            print("--- agent stderr ---", file=sys.stderr)
            print(exc.stderr, file=sys.stderr)
        return 1

    _print_summary(final)
    print(f"Wrote {os.path.join(meta.output_dir, 'report.json')}")
    print(f"Wrote {os.path.join(meta.output_dir, 'report.csv')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
