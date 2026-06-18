from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import uuid
import json
from pathlib import Path

import yaml

from icm_platform.assets import report_path_for_run
from icm_platform.db import connect, get_platform_settings, utc_now
from icm_platform.paths import DRAFT_RUN_DIR, ROOT


class RunnerWorker:
    def __init__(self) -> None:
        self._queue: queue.Queue[str] = queue.Queue()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="icm-runner-worker", daemon=True)
        self._thread.start()

    def enqueue(self, mode: str, case_id: str | None = None, draft_id: int | None = None) -> dict[str, str | None]:
        if mode not in {"run-case", "run-batch", "run-draft", "agent-explore"}:
            raise ValueError("mode must be run-case, run-batch, run-draft, or agent-explore")
        task_id = f"ui-{uuid.uuid4().hex[:12]}"
        draft_yaml_path: Path | None = None
        if mode in {"run-draft", "agent-explore"} and draft_id and not case_id:
            draft_yaml_path, case_id = self._prepare_draft_case(task_id, draft_id)
            arg = str(draft_yaml_path)
        else:
            arg = case_id if mode in {"run-case", "agent-explore"} else task_id
        if not arg:
            raise ValueError(f"case_id is required for {mode}")
        platform_run_id = task_id if mode == "run-case" else arg
        if mode == "run-draft":
            platform_run_id = task_id
        settings = get_platform_settings()
        runner_settings = settings["runner"]
        command_parts = [sys.executable, "-m", "runner.main", mode, arg, *self._runner_args(runner_settings)]
        if mode == "agent-explore":
            command_parts = [sys.executable, "-m", "runner.main", mode, arg, task_id, *self._runner_args(runner_settings)]
        if mode in {"run-case", "run-draft"}:
            command_parts.append(platform_run_id)
        command = subprocess.list2cmdline(command_parts)
        self._insert_task(task_id, mode, case_id, command)
        self._queue.put(task_id)
        return {"id": task_id, "mode": mode, "case_id": case_id, "status": "queued"}

    def enqueue_agent_self_heal(self, parent_run_id: str, case_yaml: str, healing_context: dict, case_id: str | None = None) -> dict[str, str | None]:
        task_id = f"ui-{uuid.uuid4().hex[:12]}"
        data = yaml.safe_load(case_yaml) or {}
        if not isinstance(data, dict):
            raise ValueError("case YAML root must be an object")
        resolved_case_id = str(case_id or data.get("id") or "").strip()
        if not resolved_case_id:
            raise ValueError("case_id is required for self heal")
        if not data.get("id"):
            data["id"] = resolved_case_id
        if not data.get("system"):
            data["system"] = "icm-internal"
        yaml_text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
        draft_dir = DRAFT_RUN_DIR / task_id
        draft_dir.mkdir(parents=True, exist_ok=True)
        draft_path = draft_dir / "case.yaml"
        healing_context_path = draft_dir / "healing-context.json"
        draft_path.write_text(yaml_text, encoding="utf-8")
        healing_context_path.write_text(json.dumps(healing_context, ensure_ascii=False, indent=2), encoding="utf-8")
        runner_settings = get_platform_settings()["runner"]
        command_parts = [sys.executable, "-m", "runner.main", "agent-explore", str(draft_path), task_id, *self._runner_args(runner_settings)]
        command = subprocess.list2cmdline(command_parts)
        self._insert_task(
            task_id,
            "agent-explore",
            resolved_case_id,
            command,
            parent_run_id=parent_run_id,
            trigger="self_heal",
            healing_context_path=str(healing_context_path),
        )
        self._queue.put(task_id)
        return {
            "id": task_id,
            "mode": "agent-explore",
            "case_id": resolved_case_id,
            "status": "queued",
            "parent_run_id": parent_run_id,
            "trigger": "self_heal",
        }

    def _prepare_draft_case(self, task_id: str, draft_id: int | None) -> tuple[Path, str]:
        if not draft_id:
            raise ValueError("draft_id is required for run-draft")
        with connect() as conn:
            row = conn.execute("select id, title, yaml from case_drafts where id = ?", (draft_id,)).fetchone()
        if not row:
            raise ValueError(f"case draft not found: {draft_id}")
        draft_yaml = str(row["yaml"] or "")
        try:
            data = yaml.safe_load(draft_yaml) or {}
        except yaml.YAMLError as exc:
            raise ValueError(f"draft YAML is invalid: {exc}") from exc
        case_id = str(data.get("id") or f"DRAFT-{draft_id}")
        if not data.get("id"):
            data["id"] = case_id
            draft_yaml = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
        if not data.get("system"):
            data["system"] = "icm-internal"
            draft_yaml = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
        draft_dir = DRAFT_RUN_DIR / task_id
        draft_dir.mkdir(parents=True, exist_ok=True)
        draft_path = draft_dir / "case.yaml"
        draft_path.write_text(draft_yaml, encoding="utf-8")
        return draft_path, case_id

    def _insert_task(
        self,
        task_id: str,
        mode: str,
        case_id: str | None,
        command: str,
        *,
        parent_run_id: str | None = None,
        trigger: str | None = None,
        healing_context_path: str | None = None,
    ) -> None:
        now = utc_now()
        with connect() as conn:
            conn.execute(
                """
                insert into run_tasks(id, mode, case_id, parent_run_id, trigger, healing_context_path, status, command, created_at)
                values (?, ?, ?, ?, ?, ?, 'queued', ?, ?)
                """,
                (task_id, mode, case_id, parent_run_id, trigger, healing_context_path, command, now),
            )

    def _loop(self) -> None:
        while True:
            task_id = self._queue.get()
            try:
                self._run(task_id)
            finally:
                self._queue.task_done()

    def _run(self, task_id: str) -> None:
        with connect() as conn:
            task = conn.execute("select * from run_tasks where id = ?", (task_id,)).fetchone()
            if not task:
                return
            conn.execute("update run_tasks set status = 'running', started_at = ? where id = ?", (utc_now(), task_id))

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        command = [sys.executable, "-m", "runner.main", task["mode"]]
        if task["mode"] == "agent-explore":
            draft_path = DRAFT_RUN_DIR / task["id"] / "case.yaml"
            command.extend([str(draft_path) if draft_path.exists() else task["case_id"], task["id"]])
        elif task["mode"] == "run-case":
            command.extend([task["case_id"], task["id"]])
        elif task["mode"] == "run-draft":
            command.extend([str(DRAFT_RUN_DIR / task["id"] / "case.yaml"), task["id"]])
        else:
            command.append(task["id"])
        command.extend(self._runner_args(get_platform_settings()["runner"]))
        process = subprocess.Popen(
            command,
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        assert process.stdout is not None
        for line in process.stdout:
            self._append_log(task_id, "stdout", line.rstrip())
        return_code = process.wait()

        report_path = self._resolve_report_path(task_id, task["mode"], task["case_id"])
        status = "passed" if return_code == 0 else "failed"
        with connect() as conn:
            conn.execute(
                """
                update run_tasks
                set status = ?, finished_at = ?, return_code = ?, report_path = ?, error = ?
                where id = ?
                """,
                (
                    status,
                    utc_now(),
                    return_code,
                    str(report_path) if report_path else None,
                    "" if return_code == 0 else f"runner exited with {return_code}",
                    task_id,
                ),
            )

    def _append_log(self, task_id: str, stream: str, line: str) -> None:
        with connect() as conn:
            conn.execute(
                "insert into run_logs(run_id, stream, line, created_at) values (?, ?, ?, ?)",
                (task_id, stream, line, utc_now()),
            )

    def _resolve_report_path(self, task_id: str, mode: str, case_id: str | None) -> Path | None:
        if mode == "run-batch":
            candidates = sorted((ROOT / "reports" / "runs").glob(f"{task_id}-*.md"))
            return candidates[-1] if candidates else None
        if mode == "agent-explore":
            path = ROOT / "reports" / "agent-explore" / task_id / "trace.json"
            return path if path.exists() else None
        path = report_path_for_run(task_id)
        return path if path.exists() else None

    def _runner_args(self, settings: dict) -> list[str]:
        args: list[str] = []
        headless = settings.get("browser_mode") == "background" if settings.get("browser_mode") else bool(settings.get("headless"))
        if headless:
            args.append("--headless")
        screenshot_policy = settings.get("screenshot_policy") or "latest_plus_failed_archive"
        args.extend(["--screenshot-policy", str(screenshot_policy)])
        batch_range = settings.get("batch_range") or "TC-ICM-001..TC-ICM-012"
        args.extend(["--batch-range", str(batch_range)])
        return args
