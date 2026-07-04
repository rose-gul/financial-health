"""Guardrails wrapping for the pipeline boundaries.

Validation strategy (per design):

1. **Pydantic** is the authoritative *structural* gate — types, ranges, required
   fields. It always runs and raises on any violation.
2. **Guardrails** ``Guard.for_pydantic`` runs as a second pass over the normalized
   JSON. We fail closed only when the Guard explicitly reports a validation failure;
   a benign internal quirk on already-valid data is logged to stderr, never fatal.
3. **Custom Guardrails validators** (registered with ``@register_validator``, fully
   offline — no hub account) enforce domain rules such as "category is known".

This keeps the pipeline robust while genuinely using the Guardrails library at every
inter-agent boundary.
"""

from __future__ import annotations

import json
import sys
from functools import lru_cache
from typing import Callable, Iterable, Optional, Type

from pydantic import BaseModel, ValidationError

from guardrails import Guard
from guardrails.validators import (  # type: ignore[import]
    FailResult,
    PassResult,
    Validator,
    register_validator,
)


class BoundaryValidationError(Exception):
    """Raised when a message crossing an agent boundary fails validation."""


# --------------------------------------------------------------------------- #
# Custom, offline Guardrails validators (no hub install / no account required)
# --------------------------------------------------------------------------- #
@register_validator(name="finance/known-category", data_type="string")
class KnownCategory(Validator):
    """Fail if a value is not one of the configured category names."""

    def __init__(self, allowed: Iterable[str], on_fail: Optional[Callable] = None):
        allowed_list = list(allowed)
        super().__init__(on_fail=on_fail, allowed=allowed_list)
        self._allowed = set(allowed_list)

    def validate(self, value, metadata):
        if value not in self._allowed:
            return FailResult(
                error_message=(
                    f"category '{value}' is not one of the known categories "
                    f"{sorted(self._allowed)}"
                )
            )
        return PassResult()


@register_validator(name="finance/finite-number", data_type="string")
class FiniteNumber(Validator):
    """Fail if a numeric value is NaN or infinite (defends against poisoned math)."""

    def validate(self, value, metadata):
        try:
            f = float(value)
        except (TypeError, ValueError):
            return FailResult(error_message=f"'{value}' is not a number")
        if f != f or f in (float("inf"), float("-inf")):
            return FailResult(error_message=f"'{value}' is not a finite number")
        return PassResult()


# --------------------------------------------------------------------------- #
# Guard cache + boundary validation
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=None)
def _guard_for(model_cls: Type[BaseModel]) -> Guard:
    return Guard.for_pydantic(model_cls)


def validate_payload(
    model_cls: Type[BaseModel],
    payload: dict,
    *,
    semantic_checks: Optional[Callable[[dict], None]] = None,
    run_guard: bool = True,
) -> dict:
    """Validate ``payload`` against ``model_cls`` and return the normalized dict.

    Raises :class:`BoundaryValidationError` on any structural, Guardrails, or domain
    failure. The returned dict is JSON-safe (dates as ISO strings, etc.).
    """
    # 1. Structural validation (authoritative).
    try:
        obj = model_cls(**payload)
    except ValidationError as exc:
        raise BoundaryValidationError(
            f"{model_cls.__name__} schema validation failed: {exc}"
        ) from exc
    normalized = obj.model_dump(mode="json")

    # 2. Guardrails Guard pass over the normalized output.
    if run_guard:
        try:
            outcome = _guard_for(model_cls).parse(json.dumps(normalized))
            if getattr(outcome, "validation_passed", True) is False:
                raise BoundaryValidationError(
                    f"{model_cls.__name__} Guardrails validation failed: "
                    f"{getattr(outcome, 'error', 'unknown error')}"
                )
        except BoundaryValidationError:
            raise
        except Exception as exc:  # noqa: BLE001 - never let a Guard quirk break valid data
            print(
                f"[guards] non-fatal Guard note for {model_cls.__name__}: {exc}",
                file=sys.stderr,
            )

    # 3. Domain semantic checks (use the Guardrails Validators above directly).
    if semantic_checks is not None:
        semantic_checks(normalized)

    return normalized


def check_known_categories(normalized: dict, allowed: Iterable[str]) -> None:
    """Semantic check: every categorized transaction has a known category."""
    validator = KnownCategory(allowed=allowed)
    for tx in normalized.get("transactions", []):
        result = validator.validate(tx.get("category"), {})
        if isinstance(result, FailResult):
            raise BoundaryValidationError(result.error_message)
