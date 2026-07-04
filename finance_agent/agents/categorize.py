"""categorize — assign a spending category to each transaction (rule-based; LLM optional)."""

from __future__ import annotations

from ..contracts import RunMeta
from ..guards import check_known_categories
from .. import llm
from ._base import load_yaml, log, run


def _build_rules(cfg: dict):
    categories = cfg.get("categories", {}) or {}
    default = cfg.get("default_category", "uncategorized")
    income = set(cfg.get("income_categories", []) or [])
    allowed = sorted(set(categories) | {default} | income)
    # Ordered (category, keywords) pairs; first match wins.
    rules = [(cat, [str(k).lower() for k in kws]) for cat, kws in categories.items()]
    return rules, default, income, allowed


def _match(description: str, rules) -> str:
    text = description.lower()
    for category, keywords in rules:
        if any(kw in text for kw in keywords):
            return category
    return ""


def handler(payload: dict, meta: RunMeta) -> dict:
    cfg = load_yaml(meta.categories_path)
    rules, default, income, allowed = _build_rules(cfg)

    out = []
    unmatched = []
    for tx in payload["transactions"]:
        category = _match(tx["description"], rules) or default
        out.append({**tx, "category": category})
        if category == default:
            unmatched.append(tx["description"])

    # Optional LLM assist: only re-classify the ones the rules couldn't place.
    if unmatched and llm.llm_enabled(meta):
        mapping = llm.categorize_descriptions(sorted(set(unmatched)), allowed)
        if mapping:
            for row in out:
                if row["category"] == default and row["description"] in mapping:
                    row["category"] = mapping[row["description"]]

    for row in out:
        row["is_income"] = row["category"] in income

    result = {"as_of": payload["as_of"], "transactions": out}

    # Domain semantic gate (Guardrails custom validator): every category is known.
    check_known_categories(result, allowed)

    log(f"categorized {len(out)} transactions ({len(unmatched)} fell back to '{default}')")
    return result


if __name__ == "__main__":
    run("categorize", handler)
