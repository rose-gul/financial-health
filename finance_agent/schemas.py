"""Pure Pydantic data contracts for the pipeline.

This module intentionally has NO dependency on Guardrails (which is heavy) so that
every subprocess can import it cheaply. Guardrails wrapping lives in ``guards.py``.

Data flows through the pipeline as an accumulating payload. Each step's *output*
model extends the previous one, so validation at every boundary is exact:

    IngestOutput -> CategorizeOutput -> ForecastOutput -> AdviceOutput
                 -> AlertsOutput -> ReportOutput
"""

from __future__ import annotations

from datetime import date
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------- #
# Leaf records
# --------------------------------------------------------------------------- #
class Transaction(BaseModel):
    """A single normalized transaction. ``amount`` is signed: negative = money out."""

    model_config = ConfigDict(extra="forbid")

    date: date
    description: str = Field(min_length=1)
    amount: float


class CategorizedTransaction(Transaction):
    """A transaction with a category assigned by the categorize agent."""

    category: str = Field(min_length=1)
    is_income: bool = False


class CategorySpend(BaseModel):
    """Per-category budget vs. actual vs. projected, produced by the forecast agent."""

    model_config = ConfigDict(extra="forbid")

    category: str = Field(min_length=1)
    budget: float = Field(ge=0)
    actual_spend: float = Field(ge=0)
    projected_spend: float = Field(ge=0)
    is_fixed: bool = False
    pct_of_budget: float = Field(ge=0)            # projected_spend / budget (0 if no budget)
    projected_over_budget: bool = False


class BudgetForecast(BaseModel):
    model_config = ConfigDict(extra="forbid")

    month: str = Field(min_length=7)              # e.g. "2026-06"
    days_elapsed: int = Field(ge=1, le=31)
    days_in_month: int = Field(ge=28, le=31)
    monthly_income: float = Field(ge=0)
    income_so_far: float = Field(ge=0)
    total_actual_spend: float = Field(ge=0)
    total_projected_spend: float = Field(ge=0)
    projected_month_end_savings: float            # income - projected spend; may be negative
    categories: List[CategorySpend]


class AllocationSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_class: str = Field(min_length=1)
    current_pct: float = Field(ge=0, le=100)
    target_pct: float = Field(ge=0, le=100)
    action: Literal["increase", "decrease", "hold"]


class InvestmentAdvice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    portfolio_value: float = Field(ge=0)
    savings_goal: float = Field(ge=0)
    projected_savings: float                      # from the forecast; may be negative
    on_track_for_goal: bool
    suggested_monthly_investment: float = Field(ge=0)
    emergency_fund_target: float = Field(ge=0)
    emergency_fund_progress_pct: float = Field(ge=0)
    allocation: List[AllocationSuggestion] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)


class Alert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    severity: Literal["info", "warning", "critical"]
    kind: Literal[
        "budget_overage",
        "budget_warning",
        "market_move",
        "savings_shortfall",
    ]
    title: str = Field(min_length=1)
    message: str = Field(min_length=1)
    category: Optional[str] = None
    symbol: Optional[str] = None
    value: Optional[float] = None


class Report(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of: date
    month: str
    headline: str = Field(min_length=1)
    num_transactions: int = Field(ge=0)
    num_alerts: int = Field(ge=0)
    total_actual_spend: float = Field(ge=0)
    total_projected_spend: float = Field(ge=0)
    projected_month_end_savings: float
    on_track_for_goal: bool
    top_overages: List[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Per-boundary payloads (accumulate via inheritance)
# --------------------------------------------------------------------------- #
class IngestInput(BaseModel):
    """Trigger payload for the first step. Run config lives in the envelope meta."""

    model_config = ConfigDict(extra="forbid")


class IngestOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of: date
    transactions: List[Transaction]


class CategorizeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of: date
    transactions: List[CategorizedTransaction]


class ForecastOutput(CategorizeOutput):
    forecast: BudgetForecast


class AdviceOutput(ForecastOutput):
    advice: InvestmentAdvice


class AlertsOutput(AdviceOutput):
    alerts: List[Alert]


class ReportOutput(AlertsOutput):
    report: Report
