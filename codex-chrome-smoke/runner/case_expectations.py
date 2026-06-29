from __future__ import annotations

from typing import Any


def case_expected_results(case: dict[str, Any]) -> list[str]:
    raw = case.get("expected_results")
    if raw is None:
        raw = case.get("expected")
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]
