"""Shared agent harness.

Every agent is ~15 lines: define a ``handler(payload, meta) -> dict`` and call
``run(step_name, handler)``. This harness enforces the contract for all of them:

    stdin envelope  -> validate input  -> handler  -> validate output  -> stdout payload

* Input and output are validated at the boundary via :mod:`finance_agent.guards`.
* The payload is the ONLY thing written to stdout; everything else (logs, warnings,
  tracebacks) goes to stderr — so a stray log can never corrupt the inter-agent JSON.
* Any failure prints a human-readable reason to stderr and exits non-zero, which the
  orchestrator maps to a clean ``StepError``.
"""

from __future__ import annotations

import json
import sys
import traceback
from typing import Callable, Optional

import yaml

from ..contracts import STEP_BY_NAME, Envelope, RunMeta
from ..guards import BoundaryValidationError, validate_payload

Handler = Callable[[dict, RunMeta], dict]


def log(message: str) -> None:
    """Write a log line to stderr (never stdout)."""
    print(message, file=sys.stderr)


def load_yaml(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _fail(step: str, reason: str, with_traceback: bool = False) -> "None":
    if with_traceback:
        traceback.print_exc(file=sys.stderr)
    print(f"[{step}] {reason}", file=sys.stderr)
    sys.exit(1)


def run(
    step_name: str,
    handler: Handler,
    *,
    output_semantic_checks: Optional[Callable[[dict], None]] = None,
) -> None:
    spec = STEP_BY_NAME[step_name]

    raw = sys.stdin.read()
    try:
        envelope = Envelope.model_validate_json(raw)
    except Exception as exc:  # noqa: BLE001
        _fail(step_name, f"invalid envelope on stdin: {exc}")
        return

    if envelope.step != step_name:
        _fail(step_name, f"envelope step '{envelope.step}' does not match agent '{step_name}'")
        return

    try:
        payload_in = validate_payload(spec.input_model, envelope.payload)
    except BoundaryValidationError as exc:
        _fail(step_name, f"input validation failed: {exc}")
        return

    try:
        result = handler(payload_in, envelope.meta)
    except BoundaryValidationError as exc:
        _fail(step_name, f"boundary error: {exc}")
        return
    except Exception as exc:  # noqa: BLE001
        _fail(step_name, f"handler error: {exc}", with_traceback=True)
        return

    try:
        payload_out = validate_payload(
            spec.output_model, result, semantic_checks=output_semantic_checks
        )
    except BoundaryValidationError as exc:
        _fail(step_name, f"output validation failed: {exc}")
        return

    sys.stdout.write(json.dumps(payload_out))
    sys.stdout.flush()
