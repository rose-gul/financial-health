"""Inter-agent message contract and the pipeline step registry.

The orchestrator sends each agent an :class:`Envelope` on stdin:

    { "step": "<name>", "payload": {...}, "meta": {...} }

* ``payload`` is the accumulating pipeline data (validated against the step's input
  model, transformed, then emitted validated against its output model).
* ``meta`` is run-wide context (config paths, flags) passed unchanged to every step.

The agent writes ONLY the next payload dict to stdout.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Type

from pydantic import BaseModel, ConfigDict

from . import schemas

AGENT_MODULE = "finance_agent.agents.{name}"


class RunMeta(BaseModel):
    """Run-wide context, identical for every step."""

    model_config = ConfigDict(extra="forbid")

    csv_path: str
    budget_path: str
    categories_path: str
    market_path: str
    output_dir: str
    llm_enabled: bool = False


class Envelope(BaseModel):
    """The message an agent receives on stdin."""

    model_config = ConfigDict(extra="forbid")

    step: str
    payload: dict
    meta: RunMeta


@dataclass(frozen=True)
class StepSpec:
    name: str
    input_model: Type[BaseModel]
    output_model: Type[BaseModel]
    # Whether this step is allowed the ANTHROPIC_API_KEY in its subprocess env.
    # Only categorize and advice can use the LLM; the rest never receive the key.
    needs_llm: bool = False


STEPS: List[StepSpec] = [
    StepSpec("ingest", schemas.IngestInput, schemas.IngestOutput),
    StepSpec("categorize", schemas.IngestOutput, schemas.CategorizeOutput, needs_llm=True),
    StepSpec("forecast", schemas.CategorizeOutput, schemas.ForecastOutput),
    StepSpec("advice", schemas.ForecastOutput, schemas.AdviceOutput, needs_llm=True),
    StepSpec("alerts", schemas.AdviceOutput, schemas.AlertsOutput),
    StepSpec("report", schemas.AlertsOutput, schemas.ReportOutput),
]

STEP_BY_NAME: Dict[str, StepSpec] = {s.name: s for s in STEPS}
