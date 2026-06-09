from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import uuid
from pathlib import Path

from icm_platform.assets import report_path_for_run
from icm_platform.db import connect, get_platform_settings, utc_now
from icm_platform.paths import ROOT


class RunnerWorker:
    def __init__(self) -> None:
        self._queue: queue.Queue[str] = queue.Queue()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="icm-runner-worker", daemon=True)
        self._thread.start()

    def enqueue(self, mode: str, case_id: str | None = None) -> dict[str, str | None]:
        if mode not in {"run-case", "run-batch"}:
            raise ValueError("mode must be run-case or run-batch")
        task_id = f"ui-{uuid.uuid4().hex[:12]}"
        arg = case_id if mode == "run-case" else task_id
        if not arg:
            raise ValueError("case_id is required for run-case")
        platform_run_id = task_id if mode == "run-case" else arg
        settings = get_platform_settings()
        runner_settings = settings["runner"]
        command_parts = [sys.executable, "-m", "runner.main", mode, arg, *self._runner_args(runner_settings)]
        if mode == "run-case":
            command_parts.append(platform_run_id)
        command = subprocess.list2cmdline(command_parts)
        now = utc_now()
        with connect() as conn:
            conn.execute(
                """
                insert into run_tasks(id, mode, case_id, status, command, created_at)
                values (?, ?, ?, 'queued', ?, ?)
                """,
                (task_id, mode, case_id, command, now),
            )
        self._queue.put(task_id)
        return {"id": task_id, "mode": mode, "case_id": case_id, "status": "queued"}

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
        if task["mode"] == "run-case":
            command.extend([task["case_id"], task["id"]])
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
