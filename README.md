# Finance Agent — Multi-Agent Personal-Finance Pipeline (v1)

[![pipeline](https://github.com/rose-gul/financial-health/actions/workflows/pipeline.yml/badge.svg)](https://github.com/rose-gul/financial-health/actions/workflows/pipeline.yml)

A local, privacy-first personal-finance engine built as a **multi-agent pipeline**. Each step runs
as its **own isolated subprocess**, and **every message between agents is validated with the
[Guardrails](https://www.guardrailsai.com/) library**. It categorizes your spending, forecasts your
monthly or yearly budget, gives rule-based investment/savings advice, raises alerts on budget overages and
market swings, and exports a report — all **offline, with no bank accounts or secrets required**.

```
ingest → categorize → forecast → advice → alerts → report
```

## Why this design

Three requirements drove the architecture:

1. **Guardrails everywhere** — no agent trusts another agent's output. Each boundary is validated
   (Pydantic for structure, Guardrails validators for field semantics).
2. **One agent per step** — every step is a separate program, independently runnable and testable.
3. **Steps can't interfere with each other** — each agent runs in its **own OS process** with a
   separate address space, a hard timeout, and a **trimmed environment**. A crash, hang, or bad
   output in one step is contained and reported cleanly; it can't corrupt the others.

## Quick start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements.txt

python main.py --input data/transactions.csv
```

This runs the full pipeline and writes:

- `outputs/report.json` — full structured report
- `outputs/report.csv` — per-category spend/budget/forecast for spreadsheets & tax prep

It also prints a human-readable summary with your forecast and any alerts.

## Monthly and yearly reports

Monthly is the default. Choose the reporting period and optionally a cutoff date:

```powershell
python main.py --period monthly --as-of 2026-06-30 --output-dir outputs/monthly
python main.py --period yearly --as-of 2026-12-31 --output-dir outputs/yearly
```

`--as-of` selects the calendar month or year containing that date and includes only
transactions from its start through that date. Without it, the latest date in the
CSV is used. A period with no transactions fails with a clear error. Use the last
day of a completed month/year to report actual totals without extrapolation.
Separate output directories keep monthly and yearly reports from overwriting each other.

Keep configuration amounts monthly: yearly mode multiplies category budgets,
expected income, and the savings goal by 12. Emergency-fund balances and portfolio
values are unchanged. Variable spending is projected by elapsed calendar days,
including leap years. Monthly fixed spending uses actual charges; yearly fixed
spending uses average spending per elapsed calendar month multiplied by 12
(the current month counts as one, without daily extrapolation).

For meaningful forecasts, supply complete transactions from the start of the
selected month/year through the cutoff. Missing months count as zero spending;
the app cannot distinguish missing records from no spending. The sample CSV
contains only June data, so use your full year-to-date CSV for a yearly forecast.

JSON and CSV exports identify the period, its boundaries, and the cutoff date.
JSON's `period_income` and `projected_period_end_savings` apply to both modes.
Legacy `month`, `days_in_month`, and `projected_month_end_savings` fields are
preserved for monthly runs and are null for yearly runs. `monthly_income` and
`suggested_monthly_investment` retain monthly units; `suggested_period_investment`
uses the chosen period.

## The agents

| Step | Agent | What it does |
|------|-------|--------------|
| 1 | `ingest` | Reads & normalizes the transactions CSV into validated records |
| 2 | `categorize` | Keyword-rule categorization (optional Claude assist) |
| 3 | `forecast` | Projects month- or year-end spend per category vs. your budget |
| 4 | `advice` | Savings-goal & allocation advice from mock market data (optional Claude assist) |
| 5 | `alerts` | Budget-overage and market-fluctuation alerts |
| 6 | `report` | Aggregates everything; writes `report.json` + `report.csv` |

Each agent is runnable on its own: `python -m finance_agent.agents.<step>` reads a JSON message on
stdin and writes a validated JSON message on stdout (logs go to stderr).

## Configuration

- `config/budget.yaml` — monthly income, per-category budgets, savings goals, fixed categories, and
  alert thresholds.
- `config/categories.yaml` — keyword → category rules used by the categorize agent.
- `data/transactions.csv` — your expenses (`date,description,amount`; negative = money out).
- `data/market.json` — mock market prices, daily moves, and your holdings.

## Isolation & security model

Implemented in `finance_agent/runner.py`:

- **Hard wall-clock timeout** per step; a hung agent (and its child processes) is tree-killed.
- **Trimmed environment** — agents get only the env vars they need. The **`ANTHROPIC_API_KEY` is
  passed ONLY to the `categorize` and `advice` agents**; the other four literally cannot reach the
  network/LLM because the key isn't in their environment.
- **Separate address space** per step — a crash can't corrupt the orchestrator or sibling steps.
- **Strict stdout discipline** — payload-only on stdout, logs on stderr, so a stray print can't
  corrupt the inter-agent JSON.
- **Uniform error protocol** — non-zero exit or a validation failure stops the pipeline with a clear
  `StepError`; nothing downstream runs and no partial output is written.

**Honest limits on Windows:** hard CPU/memory/file-descriptor caps aren't enforced (the POSIX
`resource` module isn't available). True resource caps would require Windows **Job Objects**
(`pywin32`), which is documented here as the upgrade path but intentionally left out of v1.

## Optional: enable the LLM

The pipeline is fully rule-based by default. To let Claude assist categorization and advice:

```powershell
copy .env.example .env      # then put your key in ANTHROPIC_API_KEY
python main.py --input data/transactions.csv --llm
```

When enabled, the `categorize` and `advice` agents route Claude output through a Guardrails `Guard`
that enforces the schema and re-asks on invalid output. All other agents stay purely deterministic.

## Roadmap (deliberately out of scope for v1)

Real bank sync (Plaid), MFA / biometric login, cross-device cloud sync & backup, mobile apps, a
dark-mode dashboard UI, PDF export (CSV is included), push notifications, an offline-viewer UI, and
emailed reports. On the isolation side: Windows Job Objects for hard resource caps.
