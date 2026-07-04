"""Optional Claude assist, behind a narrow interface.

The pipeline is fully deterministic without this module. When ``--llm`` is enabled
AND an ``ANTHROPIC_API_KEY`` is present in the (categorize/advice-only) environment,
these helpers ask Claude for a structured answer that is validated by a Guardrails
``Guard`` before use. ANY problem (no key, network error, invalid output) returns
``None`` so the caller falls back to its rule-based path — the LLM can never break a run.

Model default: ``claude-sonnet-5`` (override with FINANCE_LLM_MODEL).
"""

from __future__ import annotations

import os
import sys
from typing import Dict, List, Optional

_DEFAULT_MODEL = os.environ.get("FINANCE_LLM_MODEL", "claude-sonnet-5")


def llm_enabled(meta) -> bool:
    """True only if the run enabled the LLM and this process actually holds a key."""
    return bool(getattr(meta, "llm_enabled", False)) and bool(
        os.environ.get("ANTHROPIC_API_KEY")
    )


def _note(message: str) -> None:
    print(f"[llm] {message}", file=sys.stderr)


def categorize_descriptions(
    descriptions: List[str], allowed: List[str]
) -> Optional[Dict[str, str]]:
    """Return ``{description: category}`` for the given descriptions, or ``None``.

    Only categories in ``allowed`` are accepted (enforced via Guardrails)."""
    if not descriptions:
        return {}
    try:
        from pydantic import BaseModel, Field
        from guardrails import Guard

        class _Label(BaseModel):
            description: str
            category: str = Field(description="one of the allowed categories")

        class _Labels(BaseModel):
            labels: List[_Label]

        guard = Guard.for_pydantic(_Labels)
        prompt = (
            "Classify each bank-transaction description into exactly one of these "
            f"categories: {allowed}. Respond with the required JSON only.\n\n"
            + "\n".join(f"- {d}" for d in descriptions)
        )
        outcome = guard(
            model=_DEFAULT_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
        data = outcome.validated_output or {}
        mapping = {
            item["description"]: item["category"]
            for item in data.get("labels", [])
            if item.get("category") in allowed
        }
        return mapping or None
    except Exception as exc:  # noqa: BLE001 - LLM is best-effort only
        _note(f"categorize fallback (deterministic): {exc}")
        return None


def advice_recommendations(context: dict) -> Optional[List[str]]:
    """Return a list of short recommendation strings, or ``None`` to fall back."""
    try:
        from pydantic import BaseModel
        from guardrails import Guard

        class _Advice(BaseModel):
            recommendations: List[str]

        guard = Guard.for_pydantic(_Advice)
        prompt = (
            "You are a cautious personal-finance assistant. Given this JSON summary "
            "of the user's month, return 3-5 short, concrete, non-speculative "
            "recommendations. Do not give specific securities advice.\n\n"
            f"{context}"
        )
        outcome = guard(
            model=_DEFAULT_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
        data = outcome.validated_output or {}
        recs = [str(r) for r in data.get("recommendations", []) if str(r).strip()]
        return recs or None
    except Exception as exc:  # noqa: BLE001
        _note(f"advice fallback (deterministic): {exc}")
        return None
