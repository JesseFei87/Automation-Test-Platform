from __future__ import annotations

import ast
from hashlib import sha256
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path


class CodegenExperimentError(RuntimeError):
    """An isolated Playwright Codegen experiment cannot be started, imported, or run."""


def redact_codegen_script(script: str) -> str:
    """Compatibility helper: imported Codegen scripts are already input-safe."""
    return script


_ENV_INPUT_ACTIONS = {"fill", "press_sequentially", "select_option"}
_FILE_INPUT_ACTIONS = {"set_input_files"}


class _InputVariableTransformer(ast.NodeTransformer):
    def __init__(self) -> None:
        self.inputs: list[dict[str, str | bool]] = []

    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        if not isinstance(node.func, ast.Attribute):
            return node
        action = node.func.attr
        if action in _FILE_INPUT_ACTIONS and node.args:
            raise CodegenExperimentError("recorded file input is not supported by secure variable injection")
        if action not in _ENV_INPUT_ACTIONS or not node.args:
            return node
        value = node.args[0]
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            return node
        name = f"CODEGEN_INPUT_{len(self.inputs) + 1}"
        self.inputs.append({"name": name, "action": action, "required": True})
        node.args[0] = ast.Subscript(
            value=ast.Attribute(value=ast.Name(id="os", ctx=ast.Load()), attr="environ", ctx=ast.Load()),
            slice=ast.Constant(name),
            ctx=ast.Load(),
        )
        return node


@dataclass
class CodegenExperimentState:
    session_id: str
    start_url: str
    workspace: Path
    output_path: Path
    safe_path: Path
    process: subprocess.Popen[bytes] | None = None
    error: str | None = None
    stopped: bool = False
    source_sha256: str | None = None
    input_variables: list[dict[str, str | bool]] = field(default_factory=list)
    run_process: subprocess.Popen[bytes] | None = None
    run_status: str = "not_started"
    run_error: str | None = None
    created_at: float = field(default_factory=time.time)


class CodegenExperimentRuntime:
    """Disposable Codegen sessions isolated from Recorder and regression assets."""

    def __init__(self, *, command: str | None = None, temp_root: Path | None = None) -> None:
        self._command = command
        self._temp_root = temp_root
        self._states: dict[str, CodegenExperimentState] = {}
        self._lock = threading.Lock()

    def start(self, start_url: str) -> CodegenExperimentState:
        command = self._command or shutil.which("playwright")
        if not command:
            raise CodegenExperimentError("Playwright Codegen CLI is not installed or not available on PATH")
        session_id = uuid.uuid4().hex
        workspace = Path(tempfile.mkdtemp(prefix=f"qa-codegen-{session_id}-", dir=str(self._temp_root) if self._temp_root else None))
        output_path = workspace / "recording.py"
        args = [command, "codegen", "--target", "python-async", "--output", str(output_path), "--user-data-dir", str(workspace / "profile"), start_url]
        try:
            process = subprocess.Popen(args, shell=False, cwd=workspace, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            shutil.rmtree(workspace, ignore_errors=True)
            raise CodegenExperimentError(f"unable to start Playwright Codegen: {exc}") from exc
        state = CodegenExperimentState(session_id, start_url, workspace, output_path, workspace / "recording.safe.py", process=process)
        with self._lock:
            self._states[session_id] = state
        return state

    def get(self, session_id: str) -> CodegenExperimentState:
        with self._lock:
            state = self._states.get(session_id)
        if not state:
            raise CodegenExperimentError("Codegen experiment session was not found")
        if state.process and state.process.poll() is not None and not state.stopped and not state.error:
            state.error = "Playwright Codegen exited before the experiment was stopped"
        self._refresh_run_status(state)
        return state

    def stop(self, session_id: str, timeout: float = 8.0) -> CodegenExperimentState:
        state = self.get(session_id)
        process = state.process
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=timeout)
        state.stopped = True
        if state.output_path.exists():
            self._import_script(state)
        return state

    def read_script(self, session_id: str) -> str | None:
        state = self.get(session_id)
        if not state.stopped:
            return None
        try:
            return self._read_safe_script(state)
        except CodegenExperimentError as exc:
            state.error = f"generated Codegen script could not be imported: {exc}"
            return None

    def run(self, session_id: str, variables: dict[str, str]) -> CodegenExperimentState:
        state = self.get(session_id)
        if not state.stopped:
            raise CodegenExperimentError("stop and import the Codegen experiment before running it")
        if state.run_status == "running":
            raise CodegenExperimentError("the Codegen experiment script is already running")
        self._validate_variables(state, variables)
        script = self._read_safe_script(state)
        self._reject_literal_input_values(script, state.safe_path)
        environment = os.environ.copy()
        environment.update(variables)
        try:
            process = subprocess.Popen(
                [sys.executable, str(state.safe_path)],
                shell=False,
                cwd=state.workspace,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=environment,
            )
        except OSError as exc:
            state.run_status = "failed"
            state.run_error = "unable to start the isolated Codegen script"
            raise CodegenExperimentError(state.run_error) from exc
        state.run_process = process
        state.run_status = "running"
        state.run_error = None
        return state

    @staticmethod
    def _read_raw_script(state: CodegenExperimentState) -> str:
        if not state.output_path.exists():
            raise CodegenExperimentError("the Codegen experiment did not produce a script")
        try:
            return state.output_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise CodegenExperimentError("the original Codegen script cannot be read") from exc

    @staticmethod
    def _read_safe_script(state: CodegenExperimentState) -> str:
        if not state.safe_path.exists():
            raise CodegenExperimentError("the Codegen experiment script has not been imported")
        try:
            return state.safe_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise CodegenExperimentError("the imported Codegen script cannot be read") from exc

    def _import_script(self, state: CodegenExperimentState) -> str:
        source = self._read_raw_script(state)
        try:
            try:
                tree = ast.parse(source, filename=str(state.output_path))
            except SyntaxError as exc:
                raise CodegenExperimentError(f"generated Codegen script has invalid syntax: {exc.msg}") from exc
            state.source_sha256 = sha256(source.encode("utf-8")).hexdigest()
            transformer = _InputVariableTransformer()
            safe_tree = transformer.visit(tree)
            self._ensure_page_binding(safe_tree)
            ast.fix_missing_locations(safe_tree)
            if not any(isinstance(node, ast.Import) and any(alias.name == "os" for alias in node.names) for node in safe_tree.body):
                safe_tree.body.insert(0, ast.Import(names=[ast.alias(name="os")]))
                ast.fix_missing_locations(safe_tree)
            state.safe_path.write_text(ast.unparse(safe_tree) + "\n", encoding="utf-8")
            state.input_variables = transformer.inputs
        finally:
            try:
                state.output_path.unlink(missing_ok=True)
            except OSError as exc:
                raise CodegenExperimentError("unable to remove raw Codegen output after import") from exc
        return self._read_safe_script(state)

    @staticmethod
    def _ensure_page_binding(tree: ast.AST) -> None:
        """Repair the exact Codegen omission where `page` is used but never created."""
        run_function = next(
            (
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.AsyncFunctionDef) and node.name == "run"
            ),
            None,
        )
        if not run_function:
            return
        page_is_bound = any(
            isinstance(node, ast.Name) and node.id == "page" and isinstance(node.ctx, ast.Store)
            for node in ast.walk(run_function)
        )
        page_is_used = any(
            isinstance(node, ast.Name) and node.id == "page" and isinstance(node.ctx, ast.Load)
            for node in ast.walk(run_function)
        )
        if page_is_bound or not page_is_used:
            return
        context_index = next(
            (
                index
                for index, statement in enumerate(run_function.body)
                if isinstance(statement, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "context" for target in statement.targets)
            ),
            None,
        )
        if context_index is None:
            return
        run_function.body.insert(
            context_index + 1,
            ast.Assign(
                targets=[ast.Name(id="page", ctx=ast.Store())],
                value=ast.Await(
                    value=ast.Call(
                        func=ast.Attribute(value=ast.Name(id="context", ctx=ast.Load()), attr="new_page", ctx=ast.Load()),
                        args=[],
                        keywords=[],
                    )
                ),
            ),
        )

    @staticmethod
    def _validate_variables(state: CodegenExperimentState, variables: dict[str, str]) -> None:
        expected = {str(item["name"]) for item in state.input_variables}
        if set(variables) != expected:
            raise CodegenExperimentError("secure input variables are missing or do not match the imported script")

    @staticmethod
    def _reject_literal_input_values(script: str, output_path: Path) -> None:
        tree = ast.parse(script, filename=str(output_path))
        unsafe_methods = _ENV_INPUT_ACTIONS | _FILE_INPUT_ACTIONS
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or node.func.attr not in unsafe_methods:
                continue
            if any(isinstance(value, ast.Constant) and isinstance(value.value, (str, bytes)) for value in node.args):
                raise CodegenExperimentError("imported script contains literal input data")

    @staticmethod
    def _refresh_run_status(state: CodegenExperimentState) -> None:
        process = state.run_process
        if not process or state.run_status != "running":
            return
        exit_code = process.poll()
        if exit_code is None:
            return
        state.run_status = "succeeded" if exit_code == 0 else "failed"
        state.run_error = None if exit_code == 0 else "the isolated Codegen script exited with an error"
