from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.async_api import Page

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = ROOT / "reports" / "evidence"
TRACE_ROOT = ROOT / "reports" / "traces"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class EvidenceRecorder:
    def __init__(self, run_id: str, case_id: str) -> None:
        self.run_id = run_id
        self.case_id = case_id
        self.root = EVIDENCE_ROOT / run_id
        self.dom_dir = self.root / "dom"
        self.events_path = self.root / "events.jsonl"
        self.console_path = self.root / "console.jsonl"
        self.network_path = self.root / "network.jsonl"
        self.trace_path = TRACE_ROOT / run_id / "trace.zip"
        self._started_trace = False
        self.root.mkdir(parents=True, exist_ok=True)
        self.dom_dir.mkdir(parents=True, exist_ok=True)
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)
        self.events_path.touch(exist_ok=True)
        self.console_path.touch(exist_ok=True)
        self.network_path.touch(exist_ok=True)

    async def start(self, page: Page) -> None:
        self.attach(page)
        try:
            await page.context.tracing.start(screenshots=True, snapshots=True, sources=True)
            self._started_trace = True
            self.event(page, "trace_start", "started Playwright tracing")
        except Exception as exc:
            self.event(page, "trace_start_failed", "failed to start Playwright tracing", error=str(exc))

    async def stop(self, page: Page) -> None:
        if not self._started_trace:
            return
        try:
            await page.context.tracing.stop(path=str(self.trace_path))
            self.event(page, "trace_stop", "saved Playwright trace", path=str(self.trace_path.relative_to(ROOT)))
        except Exception as exc:
            self.event(page, "trace_stop_failed", "failed to save Playwright trace", error=str(exc))

    def attach(self, page: Page) -> None:
        setattr(page, "_evidence_recorder", self)
        if getattr(page, "_evidence_listeners_attached", False):
            return
        page.on("console", lambda message: self.console(page, message.type, message.text))
        page.on("request", lambda request: self.network(page, "request", request.method, request.url))
        page.on(
            "response",
            lambda response: self.network(
                page,
                "response",
                str(response.status),
                response.url,
            ),
        )
        setattr(page, "_evidence_listeners_attached", True)

    def event(
        self,
        page: Page,
        kind: str,
        message: str,
        *,
        selectors: list[str] | None = None,
        value: str | None = None,
        error: str | None = None,
        path: str | None = None,
    ) -> None:
        payload = self._base(page)
        payload.update(
            {
                "kind": kind,
                "message": message,
                "selectors": selectors or [],
                "value": value,
                "error": error,
                "path": path,
            }
        )
        self._append_jsonl(self.events_path, payload)

    def console(self, page: Page, level: str, text: str) -> None:
        payload = self._base(page)
        payload.update({"level": level, "text": text})
        self._append_jsonl(self.console_path, payload)

    def network(self, page: Page, kind: str, method_or_status: str, url: str) -> None:
        payload = self._base(page)
        payload.update({"kind": kind, "method_or_status": method_or_status, "url": url})
        self._append_jsonl(self.network_path, payload)

    async def dom_snapshot(self, page: Page, name: str) -> str | None:
        safe_name = name.replace("/", "_").replace("\\", "_").replace(" ", "_")
        path = self.dom_dir / safe_name
        try:
            html = await page.content()
            path.write_text(html, encoding="utf-8")
            relative = str(path.relative_to(ROOT))
            self.event(page, "dom_snapshot", f"saved DOM snapshot {name}", path=relative)
            return relative
        except Exception as exc:
            self.event(page, "dom_snapshot_failed", f"failed to save DOM snapshot {name}", error=str(exc))
            return None

    def summary(self) -> dict[str, Any]:
        return evidence_summary(self.run_id)

    def _base(self, page: Page) -> dict[str, Any]:
        try:
            title = getattr(page, "_last_known_title", "") or ""
        except Exception:
            title = ""
        return {
            "run_id": self.run_id,
            "case_id": self.case_id,
            "created_at": _utc_now(),
            "url": getattr(page, "url", ""),
            "title": title,
        }

    @staticmethod
    def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(payload, ensure_ascii=False) + "\n")


def attach_evidence_recorder(page: Page, run_id: str, case_id: str) -> EvidenceRecorder:
    recorder = EvidenceRecorder(run_id=run_id, case_id=case_id)
    recorder.attach(page)
    return recorder


def get_evidence_recorder(page: Any) -> EvidenceRecorder | None:
    return getattr(page, "_evidence_recorder", None)


def inherit_evidence_recorder(source_page: Any, target_page: Any) -> None:
    recorder = get_evidence_recorder(source_page)
    if recorder:
        recorder.attach(target_page)


def read_jsonl(path: Path, limit: int = 20) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows[-limit:]


def evidence_summary(run_id: str) -> dict[str, Any]:
    root = EVIDENCE_ROOT / run_id
    dom_dir = root / "dom"
    trace_path = TRACE_ROOT / run_id / "trace.zip"
    events_path = root / "events.jsonl"
    console_path = root / "console.jsonl"
    network_path = root / "network.jsonl"
    dom_files = sorted(dom_dir.glob("*.html")) if dom_dir.exists() else []
    return {
        "run_id": run_id,
        "root": str(root.relative_to(ROOT)) if root.exists() else "",
        "trace": {
            "exists": trace_path.exists(),
            "path": str(trace_path.relative_to(ROOT)) if trace_path.exists() else "",
            "url": f"/api/runs/{run_id}/evidence/trace" if trace_path.exists() else "",
        },
        "events": {
            "exists": events_path.exists(),
            "path": str(events_path.relative_to(ROOT)) if events_path.exists() else "",
            "count": len(read_jsonl(events_path, limit=100000)),
            "latest": read_jsonl(events_path, limit=12),
        },
        "console": {
            "exists": console_path.exists(),
            "path": str(console_path.relative_to(ROOT)) if console_path.exists() else "",
            "count": len(read_jsonl(console_path, limit=100000)),
            "latest": read_jsonl(console_path, limit=8),
        },
        "network": {
            "exists": network_path.exists(),
            "path": str(network_path.relative_to(ROOT)) if network_path.exists() else "",
            "count": len(read_jsonl(network_path, limit=100000)),
            "latest": read_jsonl(network_path, limit=8),
        },
        "dom": {
            "count": len(dom_files),
            "files": [
                {
                    "filename": path.name,
                    "path": str(path.relative_to(ROOT)),
                    "url": f"/api/runs/{run_id}/evidence/dom/{path.name}",
                }
                for path in dom_files[-8:]
            ],
        },
    }
