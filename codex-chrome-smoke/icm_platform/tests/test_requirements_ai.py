from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from icm_platform import db
from icm_platform.api import load_cached_report_analysis, load_report_analysis_versions, save_report_analysis
from icm_platform.ai_service import AIConfigurationError, AIProviderError, AIService


class RequirementAITests(unittest.TestCase):
    def test_masks_saved_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db_path = Path(folder) / "test.sqlite3"
            with patch("icm_platform.db.DB_PATH", db_path), patch("icm_platform.db.DATA_DIR", db_path.parent):
                db.init_db()
                db.save_ai_settings(
                    {
                        "provider": "minimax-m3",
                        "base_url": "https://api.minimaxi.com/v1",
                        "model": "MiniMax-M3",
                        "api_key": "sk-cp-test-123456",
                    }
                )

                settings = db.get_ai_settings(mask_key=True)

        self.assertTrue(settings["has_api_key"])
        self.assertEqual(settings["api_key_masked"], "****3456")
        self.assertNotIn("api_key", settings)

    def test_normalizes_openai_compatible_base_url(self) -> None:
        self.assertEqual(
            AIService.chat_completions_url("https://api.minimaxi.com/v1"),
            "https://api.minimaxi.com/v1/chat/completions",
        )
        self.assertEqual(
            AIService.chat_completions_url("http://192.168.12.38:11434/v1"),
            "http://192.168.12.38:11434/v1/chat/completions",
        )

    def test_normalizes_ollama_tags_url(self) -> None:
        self.assertEqual(
            AIService.ollama_tags_url("http://192.168.12.38:11434/v1"),
            "http://192.168.12.38:11434/api/tags",
        )
        self.assertEqual(
            AIService.ollama_tags_url("http://192.168.12.38:11434/v1/chat/completions"),
            "http://192.168.12.38:11434/api/tags",
        )

    def test_parse_ollama_tags(self) -> None:
        raw = {
            "models": [
                {
                    "name": "qwen3.6:35b",
                    "model": "qwen3.6:35b",
                    "modified_at": "2026-06-01T07:14:42Z",
                    "size": 23938333577,
                    "details": {"parameter_size": "36.0B", "quantization_level": "Q4_K_M"},
                }
            ]
        }

        models = AIService.parse_ollama_tags(raw)

        self.assertEqual(models[0]["model"], "qwen3.6:35b")
        self.assertEqual(models[0]["details"]["parameter_size"], "36.0B")

    def test_parse_spec_cases_wraps_invalid_json(self) -> None:
        # PRD R6 / ARCH SK-01：错误文案统一为 "模型输出格式异常"，不保留旧英文串
        with self.assertRaisesRegex(AIProviderError, "模型输出格式异常"):
            AIService._parse_spec_cases('{"cases": [{"id": "CASE_001"} {"id": "CASE_002"}]}')

    def test_parse_spec_cases_accepts_json_object_fragment(self) -> None:
        parsed = AIService._parse_spec_cases('```json\n{"cases": [{"id": "CASE_001", "title": "ok"}]}\n```')

        self.assertEqual(parsed[0]["id"], "CASE_001")

    def test_parse_chat_completion_json_response(self) -> None:
        content = {
            "test_points": [
                {
                    "name": "请求协助入口",
                    "category": "功能",
                    "priority": "P0",
                    "status": "待确认",
                    "description": "设备信息卡片中可发起请求协助",
                }
            ],
            "analysis_summary": "覆盖核心远程报修入口。",
            "risk_summary": "需要等待设备屏幕加载完成。",
            "case_count": 1,
        }
        raw = {"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]}

        parsed = AIService.parse_chat_completion(raw)

        self.assertEqual(parsed["test_points"][0].name, "请求协助入口")
        self.assertEqual(parsed["analysis_summary"], "覆盖核心远程报修入口。")
        self.assertEqual(parsed["case_count"], 1)

    def test_minimax_requires_api_key(self) -> None:
        service = AIService()

        with self.assertRaises(AIConfigurationError):
            service._validate_settings(
                {
                    "provider": "minimax-m3",
                    "api_key": "",
                    "base_url": "https://api.minimaxi.com/v1",
                    "model": "MiniMax-M3",
                }
            )

    def test_ollama_provider_does_not_require_api_key(self) -> None:
        service = AIService()

        service._validate_settings(
            {
                "provider": "ollama-local",
                "api_key": "",
                "base_url": "http://192.168.12.38:11434/v1",
                "model": "qwen3.6:35b",
            }
        )

    def test_model_request_timeout_is_provider_error(self) -> None:
        service = AIService()

        with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            with self.assertRaisesRegex(AIProviderError, "timed out after 300 seconds"):
                service._post_json("http://example.test/v1/chat/completions", "", {"model": "qwen3.6:35b"}, timeout=300)

    def test_omits_authorization_when_api_key_is_empty(self) -> None:
        self.assertEqual(AIService.request_headers(""), {"Content-Type": "application/json"})

    def test_ollama_provider_ignores_saved_api_key(self) -> None:
        self.assertEqual(
            AIService.api_key_for_provider({"provider": "ollama-local", "api_key": "sk-cp-old"}),
            "",
        )

    def test_analyze_run_report_with_ai_parses_json(self) -> None:
        service = AIService()
        raw = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "status": "failed",
                                "conclusion": "远程桌面未打开，需复查入口点击。",
                                "risks": ["截图缺少 final 阶段"],
                                "retest_suggestions": ["复跑 TC-ICM-012 并观察远程页签"],
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }

        with patch.object(service, "_post_json", return_value=raw):
            analysis = service.analyze_run_report_with_ai(
                "status: failed\nerror: remote desktop missing",
                [{"filename": "03-final.png", "case_id": "TC-ICM-012"}],
                ["open report", "missing tab"],
                {
                    "provider": "ollama-local",
                    "api_key": "",
                    "base_url": "http://127.0.0.1:11434/v1",
                    "model": "qwen3.6:35b",
                },
            )

        self.assertEqual(analysis["source"], "ai")
        self.assertEqual(analysis["status"], "failed")
        self.assertEqual(analysis["provider"], "ollama-local")
        self.assertEqual(analysis["model"], "qwen3.6:35b")
        self.assertEqual(analysis["risks"], ["截图缺少 final 阶段"])

    def test_switching_to_ollama_clears_saved_key(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db_path = Path(folder) / "test.sqlite3"
            with patch("icm_platform.db.DB_PATH", db_path), patch("icm_platform.db.DATA_DIR", db_path.parent):
                db.init_db()
                db.save_ai_settings(
                    {
                        "provider": "minimax-m3",
                        "base_url": "https://api.minimaxi.com/v1",
                        "model": "MiniMax-M3",
                        "api_key": "sk-cp-test-123456",
                    }
                )
                db.save_ai_settings(
                    {
                        "provider": "ollama-local",
                        "base_url": "http://192.168.12.38:11434/v1",
                        "model": "qwen3.6:35b",
                    }
                )

                settings = db.get_ai_settings(mask_key=True)

        self.assertFalse(settings["has_api_key"])
        self.assertEqual(settings["api_key_masked"], "")

    def test_report_analysis_cache_roundtrip(self) -> None:
        settings = {
            "provider": "ollama-local",
            "api_key": "",
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "qwen3.6:35b",
        }
        analysis = {
            "provider": "ollama-local",
            "model": "qwen3.6:35b",
            "source": "ai",
            "status": "passed",
            "conclusion": "cached result",
            "risks": [],
            "retest_suggestions": [],
            "screenshot_count": 3,
            "log_count": 2,
        }
        with tempfile.TemporaryDirectory() as folder:
            db_path = Path(folder) / "test.sqlite3"
            with patch("icm_platform.db.DB_PATH", db_path), patch("icm_platform.db.DATA_DIR", db_path.parent):
                db.init_db()
                save_report_analysis("run-1", "status: passed", settings, analysis)
                cached = load_cached_report_analysis("run-1", "status: passed", settings)
                missed = load_cached_report_analysis("run-1", "status: changed", settings)

        self.assertIsNotNone(cached)
        self.assertEqual(cached["conclusion"], "cached result")
        self.assertTrue(cached["cached"])
        self.assertIsNone(missed)

    def test_report_analysis_versions_keep_history(self) -> None:
        settings = {
            "provider": "ollama-local",
            "api_key": "",
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "qwen3.6:35b",
        }
        first = {
            "provider": "ollama-local",
            "model": "qwen3.6:35b",
            "source": "ai",
            "status": "failed",
            "conclusion": "first result",
            "risks": [],
            "retest_suggestions": [],
            "screenshot_count": 1,
            "log_count": 1,
        }
        second = {**first, "conclusion": "second result"}
        with tempfile.TemporaryDirectory() as folder:
            db_path = Path(folder) / "test.sqlite3"
            with patch("icm_platform.db.DB_PATH", db_path), patch("icm_platform.db.DATA_DIR", db_path.parent):
                db.init_db()
                save_report_analysis("run-2", "status: failed", settings, first)
                save_report_analysis("run-2", "status: failed", settings, second)
                cached = load_cached_report_analysis("run-2", "status: failed", settings)
                versions = load_report_analysis_versions("run-2", "status: failed")

        self.assertEqual(cached["conclusion"], "second result")
        self.assertEqual(len(versions), 2)
        self.assertEqual(versions[0]["analysis"]["conclusion"], "second result")
        self.assertEqual(versions[1]["analysis"]["conclusion"], "first result")


if __name__ == "__main__":
    unittest.main()
