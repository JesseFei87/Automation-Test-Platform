from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from icm_platform.codegen_experiment_runtime import CodegenExperimentRuntime


class CodegenExperimentRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.runtime = CodegenExperimentRuntime(command="playwright", temp_root=self.root)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    @patch("icm_platform.codegen_experiment_runtime.subprocess.Popen")
    def test_import_replaces_literals_with_environment_variables_and_removes_raw_output(self, popen: Mock) -> None:
        process = Mock()
        process.poll.return_value = None
        popen.return_value = process
        state = self.runtime.start("https://example.test/login")
        literal = "do-not-persist"
        state.output_path.write_text(
            "async def test_example(page):\n    await page.get_by_label('password').fill('do-not-persist')\n",
            encoding="utf-8",
        )

        self.runtime.stop(state.session_id)
        preview = self.runtime.read_script(state.session_id) or ""

        self.assertFalse(state.output_path.exists())
        self.assertIn("os.environ['CODEGEN_INPUT_1']", preview)
        self.assertNotIn(literal, preview)
        self.assertEqual(state.input_variables, [{"name": "CODEGEN_INPUT_1", "action": "fill", "required": True}])

    @patch("icm_platform.codegen_experiment_runtime.subprocess.Popen")
    def test_import_restores_missing_page_initialization_before_page_is_used(self, popen: Mock) -> None:
        process = Mock()
        process.poll.return_value = None
        popen.return_value = process
        state = self.runtime.start("https://example.test/login")
        state.output_path.write_text(
            "async def run(playwright):\n    context = await playwright.chromium.launch()\n    await page.goto('https://example.test')\n",
            encoding="utf-8",
        )

        self.runtime.stop(state.session_id)
        script = self.runtime.read_script(state.session_id) or ""

        self.assertIn("page = await context.new_page()", script)
        compile(script, str(state.safe_path), "exec")

    @patch("icm_platform.codegen_experiment_runtime.subprocess.Popen")
    def test_runs_sanitized_script_with_one_process_only_variables(self, popen: Mock) -> None:
        codegen_process = Mock()
        codegen_process.poll.return_value = None
        runner_process = Mock()
        runner_process.poll.return_value = None
        popen.side_effect = [codegen_process, runner_process]
        state = self.runtime.start("https://example.test/login")
        state.output_path.write_text("async def test_example(page):\n    await page.get_by_label('username').fill('tester')\n", encoding="utf-8")
        self.runtime.stop(state.session_id)

        self.runtime.run(state.session_id, {"CODEGEN_INPUT_1": "runtime-only"})

        kwargs = popen.call_args_list[1].kwargs
        self.assertEqual(popen.call_args_list[1].args[0][-1], str(state.safe_path))
        self.assertEqual(kwargs["env"]["CODEGEN_INPUT_1"], "runtime-only")
        self.assertNotIn("runtime-only", self.runtime.read_script(state.session_id) or "")
        self.assertNotIn("runtime-only", repr(state))

    @patch("icm_platform.codegen_experiment_runtime.subprocess.Popen")
    def test_rejects_missing_or_extra_runtime_variables(self, popen: Mock) -> None:
        process = Mock()
        process.poll.return_value = None
        popen.return_value = process
        state = self.runtime.start("https://example.test/login")
        state.output_path.write_text("async def test_example(page):\n    await page.get_by_label('username').fill('tester')\n", encoding="utf-8")
        self.runtime.stop(state.session_id)

        with self.assertRaisesRegex(RuntimeError, "variables are missing"):
            self.runtime.run(state.session_id, {})
        with self.assertRaisesRegex(RuntimeError, "variables are missing"):
            self.runtime.run(state.session_id, {"CODEGEN_INPUT_1": "x", "OTHER": "y"})
        self.assertEqual(popen.call_count, 1)

    @patch("icm_platform.codegen_experiment_runtime.subprocess.Popen")
    def test_rejects_file_recording_without_persisting_a_safe_copy(self, popen: Mock) -> None:
        process = Mock()
        process.poll.return_value = None
        popen.return_value = process
        state = self.runtime.start("https://example.test/login")
        state.output_path.write_text("async def test_example(page):\n    await page.set_input_files('C:/secret.txt')\n", encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "file input"):
            self.runtime.stop(state.session_id)
        self.assertFalse(state.safe_path.exists())
        self.assertFalse(state.output_path.exists())


if __name__ == "__main__":
    unittest.main()
