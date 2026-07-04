"""Pipeline orchestrator — drives the step registry, one isolated subprocess at a time.

For each step it builds an :class:`Envelope`, runs the agent via
:func:`finance_agent.runner.run_step` (timeout + trimmed env + tree-kill), surfaces the
agent's stderr, and feeds the validated output forward. Any :class:`StepError` stops the
pipeline cleanly — no downstream step runs.
"""

from __future__ import annotations

import sys
from typing import Callable, Optional

from .contracts import STEPS, Envelope, RunMeta
from .runner import StepError, run_step  # re-exported for callers


def run_pipeline(
    meta: RunMeta,
    *,
    project_root: str,
    timeout: float = 30.0,
    log: Optional[Callable[[str], None]] = None,
) -> dict:
    """Run all steps in order and return the final payload (a ReportOutput dict).

    Raises :class:`StepError` if any step fails.
    """
    emit = log or (lambda m: print(m, file=sys.stderr))

    payload: dict = {}  # IngestInput trigger
    for spec in STEPS:
        tag = "(llm-capable)" if spec.needs_llm and meta.llm_enabled else ""
        emit(f"-> {spec.name} {tag}".rstrip())
        envelope = Envelope(step=spec.name, payload=payload, meta=meta).model_dump(mode="json")
        out, stderr = run_step(spec, envelope, project_root=project_root, timeout=timeout)
        for line in stderr.splitlines():
            emit(f"   {line}")
        payload = out

    return payload
