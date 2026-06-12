"""路线 C · T14 单测：YAML → Python codegen + py_compile 自检 + 落盘回滚。

覆盖 4 个场景（任务书 §T14）：
  1) test_dry_run_success            — 6 步 operation_steps 全部命中关键词，ok=true 含 code
  2) test_missing_operation_steps    — 空 operation_steps 返回 ok=false, errors=["missing operation_steps"]
  3) test_unsupported_step_kind      — 含未命中关键词的步骤，返回 errors
  4) test_write_with_py_compile_failure_rolls_back
                                       — 强制模板渲染出语法错误，write=true 时不应落盘
"""
from __future__ import annotations

import json
import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from icm_platform import db
from icm_platform.api import (
    CodegenRequest,
    compute_target_path,
    post_codegen,
    validate_operation_steps,
)


# ==== 测试基础设施 ====

SAMPLE_CASE_YAML = textwrap.dedent(
    """
    id: TC-ICM-TEST
    title: codegen test case
    status: 已确认
    system: icm-internal
    priority: P1
    category: action
    steps:
      - "打开设备列表"
      - "在搜索框输入关键字"
    expected_results:
      - "设备列表可见"
    failure_signals:
      - "页面无响应"
    evidence_points:
      - "01-entry.png"
    risk_notes: []
    automation_asset:
      operation_steps: __OP_STEPS__
      selectors:
        device_query_input:
          - "placeholder=请输入设备名称"
        search_button:
          - "button:has-text(搜索)"
      input_values:
        device_keyword: "AU5800"
      assertions:
        - "列表显示 AU5800"
    """
).strip()


SAMPLE_TEMPLATE = textwrap.dedent(
    """
    # minimal template for unit tests
    CASE_ID = "{{ case_id }}"
    STEPS = {{ operation_steps | tojson }}
    KW = {{ (input_values.get("device_keyword") if input_values else "") | tojson }}
    TEMPLATE = "{{ template }}"
    """
).lstrip()


def _try_import_app():
    try:
        from icm_platform.api import app
        return app
    except Exception:  # noqa: BLE001
        return None


_client_app = _try_import_app()


def _make_test_world() -> tuple[Path, Path, Path, Path]:
    """建立临时项目根，含 runner/flows/templates/ 与 test-cases/icm/。"""
    folder = Path(tempfile.mkdtemp())
    root = folder
    db_path = root / "test.sqlite3"
    case_dir = root / "test-cases" / "icm"
    template_dir = root / "runner" / "flows" / "templates"
    flows_dir = root / "runner" / "flows"
    case_dir.mkdir(parents=True)
    template_dir.mkdir(parents=True)
    flows_dir.mkdir(parents=True, exist_ok=True)
    # 写一个最小 Jinja2 模板
    (template_dir / "icm_case.py.j2").write_text(SAMPLE_TEMPLATE, encoding="utf-8")
    return root, db_path, case_dir, template_dir


def _write_case_yaml(case_dir: Path, case_id: str, op_steps: list[str] | str) -> Path:
    """写一个 case YAML；op_steps 传 "__OP_STEPS__" 用占位，list/str 直接替换。"""
    if op_steps == "__OP_STEPS__":
        # 默认 6 步全部命中关键词
        steps_yaml = (
            "\n      - \"登录并准备会话\"\n"
            "      - \"打开设备列表\"\n"
            "      - \"在搜索框输入 AU5800\"\n"
            "      - \"点击搜索按钮\"\n"
            "      - \"断言页面含 AU5800\"\n"
            "      - \"等待 1 秒\"\n      "
        )
    elif isinstance(op_steps, list):
        if not op_steps:
            steps_yaml = " []\n    "
        else:
            lines = "\n".join(f'      - "{s}"' for s in op_steps)
            steps_yaml = "\n" + lines + "\n      "
    else:
        steps_yaml = f" {op_steps}\n    "
    yaml_text = SAMPLE_CASE_YAML.replace("__OP_STEPS__", steps_yaml)
    # 修正 case_id
    yaml_text = yaml_text.replace("TC-ICM-TEST", case_id)
    path = case_dir / f"{case_id.lower()}-test.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    return path


# ==== 纯函数单测（不需要 DB / 文件系统） ====

class PureFunctionTests(unittest.TestCase):
    def test_validate_operation_steps_empty(self):
        errs = validate_operation_steps([])
        self.assertEqual(errs, ["missing operation_steps"])

    def test_validate_operation_steps_none(self):
        errs = validate_operation_steps(None)  # type: ignore[arg-type]
        self.assertEqual(errs, ["missing operation_steps"])

    def test_validate_operation_steps_all_hit(self):
        steps = [
            "登录准备会话",
            "打开设备列表",
            "在搜索框输入 AU5800",
            "点击搜索按钮",
            "断言页面含 AU5800",
            "等待 1 秒",
        ]
        self.assertEqual(validate_operation_steps(steps), [])

    def test_validate_operation_steps_unsupported(self):
        steps = ["登录", "执行某段 magic 咒语"]
        errs = validate_operation_steps(steps)
        self.assertTrue(any("unsupported step kind" in e for e in errs), errs)
        self.assertTrue(any("magic 咒语" in e for e in errs), errs)

    def test_validate_operation_steps_empty_string_entry(self):
        errs = validate_operation_steps(["登录", "   "])
        self.assertTrue(any("empty" in e for e in errs), errs)

    def test_compute_target_path_naming_rule(self):
        # TC-ICM-013 -> icm_case_013.py
        self.assertEqual(compute_target_path("TC-ICM-013").name, "icm_case_013.py")
        # 大小写不敏感（uppercase case_id 也走同一条规则）
        self.assertEqual(compute_target_path("tc-icm-013").name, "icm_case_013.py")
        # 没有 TC-ICM- 前缀时回退到末段数字
        self.assertEqual(compute_target_path("CUSTOM-9").name, "icm_case_9.py")
        # 完全没有数字时回退到小写 case_id
        self.assertEqual(compute_target_path("MyCase").name, "icm_case_mycase.py")


# ==== 端点级单测（需要 mock DB + ROOT） ====

@unittest.skipIf(_client_app is None, "依赖未安装，跳过 endpoint 测试")
class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.world = _make_test_world()
        self.root, self.db_path, self.case_dir, self.template_dir = self.world
        self._patchers = [
            patch("icm_platform.db.DB_PATH", self.db_path),
            patch("icm_platform.db.DATA_DIR", self.root),
            patch("icm_platform.api.ROOT", self.root),
            patch("icm_platform.api.TEST_CASE_DIR", self.case_dir),
            patch("icm_platform.api.CODEGEN_TEMPLATE_DIR", self.template_dir),
            patch("icm_platform.api.FLOW_BACKUP_DIR", self.root / ".codex-tmp" / "flow-backup"),
        ]
        for p in self._patchers:
            p.start()
        db.init_db()
        from icm_platform import api as api_module
        self.api = api_module

    def tearDown(self):
        for p in self._patchers:
            p.stop()
        shutil.rmtree(self.world[0], ignore_errors=True)

    # ---- 1) test_dry_run_success ----
    def test_dry_run_success(self):
        _write_case_yaml(self.case_dir, "TC-ICM-013", "__OP_STEPS__")
        body = self.api.post_codegen("TC-ICM-013", CodegenRequest(write=False))
        self.assertTrue(body["ok"], body)
        self.assertEqual(body["written"], False)
        self.assertIn("TC-ICM-013", body["code"])
        self.assertIn("AU5800", body["code"])  # 输入值进入模板
        self.assertEqual(body["errors"], [])
        # target_path 符合命名规则
        self.assertTrue(body["target_path"].endswith("icm_case_013.py"))

    # ---- 2) test_missing_operation_steps ----
    def test_missing_operation_steps(self):
        _write_case_yaml(self.case_dir, "TC-ICM-013", [])
        body = self.api.post_codegen("TC-ICM-013", CodegenRequest(write=False))
        self.assertFalse(body["ok"])
        self.assertIn("missing operation_steps", body["errors"])
        self.assertEqual(body["code"], "")
        # dry-run 不应写盘
        self.assertFalse(Path(body["target_path"]).exists())

    # ---- 3) test_unsupported_step_kind ----
    def test_unsupported_step_kind(self):
        _write_case_yaml(
            self.case_dir,
            "TC-ICM-013",
            ["登录", "执行某段 magic 咒语", "断言结果正确"],
        )
        body = self.api.post_codegen("TC-ICM-013", CodegenRequest(write=False))
        self.assertFalse(body["ok"])
        self.assertTrue(any("unsupported step kind" in e for e in body["errors"]), body["errors"])
        # 但 code 仍然渲染了（dry-run 总是返回 code）
        self.assertIn("TC-ICM-013", body["code"])

    # ---- 4) test_write_with_py_compile_failure_rolls_back ----
    def test_write_with_py_compile_failure_rolls_back(self):
        _write_case_yaml(self.case_dir, "TC-ICM-013", "__OP_STEPS__")
        target = self.api.compute_target_path("TC-ICM-013")
        # 强制 _render_codegen_template 返回语法错误的 Python 源码
        broken_code = "def run(page, system, case) -> None:\n    this is :: not valid :: python @@@\n"
        with patch.object(self.api, "_render_codegen_template", return_value=broken_code):
            # 预期：内存 py_compile 失败 → 不会调用 write 路径
            body_dry = self.api.post_codegen("TC-ICM-013", CodegenRequest(write=True))
        self.assertFalse(body_dry["ok"], body_dry)
        self.assertTrue(any("py_compile failed" in e for e in body_dry["errors"]), body_dry["errors"])
        # 文件不应被创建
        self.assertFalse(target.exists(), f"目标文件不应存在，但找到了: {target}")
        # 也验证：如果 py_compile 在落盘后才失败，应回滚（已存在的旧文件）
        target.parent.mkdir(parents=True, exist_ok=True)
        original = "# original content\nasync def run(page, system, case):\n    pass\n"
        target.write_text(original, encoding="utf-8")
        with patch.object(self.api, "_render_codegen_template", return_value=broken_code):
            body_write = self.api.post_codegen("TC-ICM-013", CodegenRequest(write=True))
        self.assertFalse(body_write["ok"], body_write)
        # 落盘文件应被回滚到原始内容
        self.assertTrue(target.exists())
        self.assertEqual(target.read_text(encoding="utf-8"), original)

    # ---- 辅助：validate_case_yaml 触发 codegen 早期返回 ----
    def test_yaml_validation_failure_returns_early(self):
        # 写一个缺 automation_asset 的 YAML（validation 必失败）
        bad_path = self.case_dir / "tc-icm-bad.yaml"
        bad_path.write_text(
            textwrap.dedent(
                """
                id: TC-ICM-BAD
                title: bad case
                status: 已确认
                steps: ["s1"]
                expected_results: ["e1"]
                """
            ).strip(),
            encoding="utf-8",
        )
        body = self.api.post_codegen("TC-ICM-BAD", CodegenRequest(write=False))
        self.assertFalse(body["ok"])
        self.assertTrue(len(body["errors"]) > 0)
        self.assertEqual(body["code"], "")

    # ---- 辅助：write=true 成功落盘 → py_compile 落盘文件 ----
    def test_write_success_creates_file(self):
        _write_case_yaml(self.case_dir, "TC-ICM-013", "__OP_STEPS__")
        target = self.api.compute_target_path("TC-ICM-013")
        body = self.api.post_codegen("TC-ICM-013", CodegenRequest(write=True))
        self.assertTrue(body["ok"], body)
        self.assertTrue(body.get("written"))
        self.assertTrue(target.exists())
        # 落盘文件可被 py_compile 编译
        import py_compile as _pc
        _pc.compile(str(target), doraise=True)
        # run_logs 应有 codegen 记录
        with db.connect() as conn:
            rows = conn.execute(
                "select line from run_logs where stream = 'codegen' order by id desc limit 1"
            ).fetchall()
        self.assertTrue(len(rows) >= 1, "run_logs 应至少有一条 codegen 记录")
        self.assertIn("write ok", rows[0]["line"])

    # ---- 7) P1：py_compile 在落盘后失败时回滚路径（mock 入口） ----
    def test_disk_py_compile_failure_rolls_back_existing_file(self):
        """落盘后 py_compile 失败（mock 抛 PyCompileError），文件应回滚到原内容。

        步骤：
          1. 写一个空目录；
          2. 预先放置"旧" target.py；
          3. patch 掉 api.py 模块级 py_compile.compile 的"文件路径"分支，
             让它抛 PyCompileError；
          4. 调用 post_codegen(write=True)；
          5. 断言：ok=false, errors 含 "rolled back"，文件内容等于原"旧"内容。
        """
        import logging
        import py_compile

        _write_case_yaml(self.case_dir, "TC-ICM-013", "__OP_STEPS__")
        target = self.api.compute_target_path("TC-ICM-013")
        target.parent.mkdir(parents=True, exist_ok=True)
        original = "# ORIGINAL old content (must survive rollback)\nasync def run(page, system, case):\n    pass\n"
        target.write_text(original, encoding="utf-8")

        real_compile = py_compile.compile

        def fake_compile(path_to_py, *args, **kwargs):
            # api.py 调用方式：py_compile.compile(str(target_path), doraise=True)
            # 只对真实存在的 .py 文件抛错（避免误命中其他路径上的 compile）
            if isinstance(path_to_py, str) and path_to_py.endswith(".py") and Path(path_to_py).exists():
                # PyCompileError(exc_type, exc_value, file, msg='')，exc_value 必须是 SyntaxError 实例
                raise py_compile.PyCompileError(
                    SyntaxError,
                    SyntaxError(
                        "SIMULATED: invalid syntax (mocked for rollback test)",
                        ("fake.py", 5, 1, "    broken indent"),
                    ),
                    "fake.py",
                )
            return real_compile(path_to_py, *args, **kwargs)

        caplog = self.assertLogs("icm_platform.api", level=logging.INFO) if hasattr(self, "assertLogs") else None
        with patch.object(self.api.py_compile, "compile", side_effect=fake_compile):
            body = self.api.post_codegen("TC-ICM-013", CodegenRequest(write=True))

        # 1) 端点响应正确
        self.assertFalse(body["ok"], body)
        self.assertFalse(body.get("written"))
        self.assertTrue(
            any("rolled back" in e for e in body["errors"]),
            f"errors 应含 'rolled back': {body['errors']}",
        )
        # 2) 文件被回滚到原内容
        self.assertTrue(target.exists(), "rollback 后文件应仍存在（恢复自 backup）")
        self.assertEqual(
            target.read_text(encoding="utf-8"),
            original,
            "rollback 后文件内容应等于原始内容",
        )
        # 3) 没有遗留 .tmp / .bak
        backup_dir = self.root / ".codex-tmp" / "flow-backup"
        self.assertTrue(backup_dir.exists(), "rollback 路径应创建过 .codex-tmp/flow-backup/")
        leftovers = [
            p for p in backup_dir.iterdir()
            if p.suffix in {".tmp", ".bak"} and p.name != p.name + ".tmp"
        ]
        self.assertEqual(leftovers, [], f"不应有 .tmp / .bak 残留: {leftovers}")
        # 4) run_logs 记录可观测的 rollback 事件
        with db.connect() as conn:
            rows = conn.execute(
                "select line from run_logs where stream='codegen' and line like '%rollback%' order by id desc limit 5"
            ).fetchall()
        rollback_lines = [r["line"] for r in rows]
        self.assertTrue(
            any("rolled back" in line for line in rollback_lines),
            f"run_logs 应有 'rolled back' 记录: {rollback_lines}",
        )

    def test_disk_py_compile_failure_removes_newly_created_file(self):
        """落盘后 py_compile 失败时，若 target 在落盘前不存在，应被删除。"""
        import py_compile

        _write_case_yaml(self.case_dir, "TC-ICM-014", "__OP_STEPS__")
        target = self.api.compute_target_path("TC-ICM-014")
        # target 一定不存在（首次生成）
        if target.exists():
            target.unlink()

        real_compile = py_compile.compile

        def fake_compile(path_to_py, *args, **kwargs):
            if isinstance(path_to_py, str) and path_to_py.endswith(".py") and Path(path_to_py).exists():
                raise py_compile.PyCompileError(
                    SyntaxError,
                    SyntaxError("SIMULATED", ("f.py", 1, 0, "x")),
                    "f.py",
                )
            return real_compile(path_to_py, *args, **kwargs)

        with patch.object(self.api.py_compile, "compile", side_effect=fake_compile):
            body = self.api.post_codegen("TC-ICM-014", CodegenRequest(write=True))

        self.assertFalse(body["ok"], body)
        self.assertTrue(any("rolled back" in e for e in body["errors"]), body["errors"])
        # 首次生成 + 失败 → 文件应被清理
        self.assertFalse(
            target.exists(),
            f"首次生成失败后，新文件应被删除，但找到: {target}",
        )


if __name__ == "__main__":
    unittest.main()
