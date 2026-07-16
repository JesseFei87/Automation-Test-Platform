from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from icm_platform import db, recorder
from icm_platform import api


class RecorderApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.db_path = self.root / "platform.sqlite3"
        self.patchers = [
            patch("icm_platform.db.DB_PATH", self.db_path),
            patch("icm_platform.db.DATA_DIR", self.root),
            patch.object(api.recorder_runtime, "start"),
            patch.object(api.recorder_runtime, "stop"),
        ]
        for patcher in self.patchers:
            patcher.start()
        db.init_db()

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def test_create_session_accepts_only_configured_origin(self) -> None:
        created = api.create_recorder_session(api.RecorderStartRequest(start_url="https://192.168.16.203:49187/#/login"))

        self.assertEqual(created["status"], "recording")
        self.assertEqual(created["steps"], [])
        with self.assertRaises(HTTPException) as caught:
            api.create_recorder_session(api.RecorderStartRequest(start_url="https://outside.example/login"))
        self.assertEqual(caught.exception.status_code, 400)

    def test_start_request_accepts_the_existing_entry_url_client_field(self) -> None:
        request = api.RecorderStartRequest.model_validate({"entry_url": "https://192.168.16.203:49187/#/login"})

        self.assertEqual(request.start_url, "https://192.168.16.203:49187/#/login")

    def test_stop_generates_candidate_and_redacts_sensitive_input(self) -> None:
        created = api.create_recorder_session(api.RecorderStartRequest(start_url="https://192.168.16.203:49187/#/login"))
        with db.connect() as conn:
            recorder.append_action(
                conn,
                created["id"],
                {
                    "type": "fill",
                    "name": "password",
                    "value": "do-not-persist",
                    "locator_candidates": [{"strategy": "testid", "value": "password", "unique": True}],
                },
            )
        stopped = api.stop_recorder_session(created["id"])

        self.assertEqual(stopped["status"], "stopped")
        self.assertEqual(stopped["steps"][0]["value"], "[redacted]")
        candidate = api.create_recorder_candidate(created["id"])["candidate"]
        self.assertIn("${SECRET}", candidate["yaml"])
        self.assertNotIn("do-not-persist", candidate["playwright_python"])
        self.assertIn("manual assertions", " ".join(candidate["blocking_warnings"]))

    def test_sse_route_exposes_event_stream(self) -> None:
        created = api.create_recorder_session(api.RecorderStartRequest(start_url="https://192.168.16.203:49187/#/login"))
        response = api.recorder_events_stream(created["id"])

        self.assertEqual(response.media_type, "text/event-stream")
        self.assertEqual(response.headers["cache-control"], "no-cache")

    def test_codegen_experiment_is_a_separate_non_promotable_session(self) -> None:
        class _State:
            session_id = "codegen-experiment-1"

        with patch.object(api.codegen_experiment_runtime, "start", return_value=_State()), patch.object(
            api.codegen_experiment_runtime, "get"
        ) as get_state:
            state = type("State", (), {"process": None, "stopped": False, "error": None, "start_url": "https://192.168.16.203:49187/#/login"})()
            get_state.return_value = state
            with patch.object(api.codegen_experiment_runtime, "read_script", return_value=None):
                created = api.create_codegen_experiment(api.CodegenExperimentStartRequest(start_url=state.start_url))

        self.assertEqual(created["mode"], "codegen-experiment")
        self.assertEqual(created["status"], "failed")
        self.assertNotIn("candidate", created)

    def test_codegen_experiment_run_has_no_script_payload_and_returns_run_state(self) -> None:
        state = type(
            "State",
            (),
            {
                "process": None,
                "stopped": True,
                "error": None,
                "start_url": "https://192.168.16.203:49187/#/login",
                "run_status": "running",
                "run_error": None,
            },
        )()
        with patch.object(api.codegen_experiment_runtime, "run", return_value=state) as run, patch.object(
            api.codegen_experiment_runtime, "get", return_value=state
        ), patch.object(api.codegen_experiment_runtime, "read_script", return_value="[redacted preview]"):
            body = api.run_codegen_experiment(
                "codegen-experiment-1",
                api.CodegenExperimentRunRequest(variables={"CODEGEN_INPUT_1": "runtime-only"}),
            )

        run.assert_called_once_with("codegen-experiment-1", {"CODEGEN_INPUT_1": "runtime-only"})
        self.assertEqual(body["run"]["status"], "running")
        self.assertNotIn("source", body)
        self.assertNotIn("runtime-only", str(body))

    def test_failed_session_exposes_persisted_certificate_prerequisite(self) -> None:
        created = api.create_recorder_session(api.RecorderStartRequest(start_url="https://192.168.16.203:49187/#/login"))
        with db.connect() as conn:
            recorder.fail_session(conn, created["id"], "录制未启动：入口证书不受信任。请安装企业根 CA 或配置有效证书后重试。")

        session = api.get_recorder_session(created["id"])

        self.assertEqual(session["status"], "failed")
        self.assertIn("企业根 CA", session["error"])


if __name__ == "__main__":
    unittest.main()
