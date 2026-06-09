from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
OBSERVED_ASSET_ROOT = ROOT / "reports" / "observed-assets"


@dataclass(slots=True)
class AssetRecorder:
    run_id: str
    case_id: str
    operation_steps: list[str] = field(default_factory=list)
    selectors: dict[str, list[str]] = field(default_factory=dict)
    input_values: dict[str, str] = field(default_factory=dict)
    assertions: list[str] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    _index: int = 0

    def route(self, route: str) -> None:
        self._record("route", f"Open route {route}", [route])

    def click(self, selectors: Iterable[str]) -> None:
        self._record("click", "Click visible control", selectors)

    def fill(self, selectors: Iterable[str], value: str) -> None:
        key = self._record("fill", "Fill visible field", selectors)
        self.input_values[key] = value

    def select(self, selectors: Iterable[str], value: str) -> None:
        key = self._record("select", f"Select option {value}", selectors)
        self.input_values[key] = value

    def assert_text(self, text: str) -> None:
        self.assertions.append(f"Text is visible: {text}")

    def screenshot(self, path: str) -> None:
        if path not in self.screenshots:
            self.screenshots.append(path)

    def to_asset(self, status: str) -> dict[str, Any]:
        return {
            "status": "observed" if status == "passed" else "failed_observed",
            "source": "playwright_observed",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "evidence": {
                "run_id": self.run_id,
                "report_path": f"reports/runs/{self.run_id}.md",
                "screenshots": self.screenshots,
            },
            "operation_steps": self.operation_steps,
            "selectors": self.selectors,
            "input_values": self.input_values,
            "assertions": self.assertions,
        }

    def _record(self, kind: str, description: str, selectors: Iterable[str]) -> str:
        self._index += 1
        key = f"{kind}_{self._index:03d}"
        values = [value for value in selectors if value]
        self.operation_steps.append(description)
        self.selectors[key] = values
        return key


def attach_asset_recorder(page: Any, run_id: str, case_id: str) -> AssetRecorder:
    recorder = AssetRecorder(run_id=run_id, case_id=case_id)
    setattr(page, "_asset_recorder", recorder)
    return recorder


def inherit_asset_recorder(source_page: Any, target_page: Any) -> None:
    recorder = get_asset_recorder(source_page)
    if recorder:
        setattr(target_page, "_asset_recorder", recorder)


def get_asset_recorder(page: Any) -> AssetRecorder | None:
    return getattr(page, "_asset_recorder", None)


def write_observed_asset(recorder: AssetRecorder, status: str) -> Path:
    OBSERVED_ASSET_ROOT.mkdir(parents=True, exist_ok=True)
    path = OBSERVED_ASSET_ROOT / f"{recorder.run_id}.json"
    path.write_text(json.dumps(recorder.to_asset(status), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def observed_asset_path(run_id: str) -> Path:
    return OBSERVED_ASSET_ROOT / f"{run_id}.json"

