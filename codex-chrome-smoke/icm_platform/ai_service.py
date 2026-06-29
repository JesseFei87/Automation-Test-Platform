from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import re


class AIConfigurationError(RuntimeError):
    pass


class AIProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class TestPoint:
    name: str
    category: str
    priority: str
    status: str = "待确认"
    description: str = ""


# -----------------------------------------------------------------------------
# P0 / P1 · 增量：prompt 分段函数（架构 §2 决策 3）
# Block = {title, rows: [(k, v), ...]}；空段整段省略
# -----------------------------------------------------------------------------


def _non_empty(value: object) -> str | None:
    """空值归一：None / 空字符串 / 全空白 → None（视作未填）；否则 strip。"""
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return str(value)


def build_project_block(project: dict[str, Any] | None) -> dict[str, Any] | None:
    """P0 · 「## 项目信息」段：name / base_url / description；任一非空即输出。"""
    if not isinstance(project, dict):
        return None
    name = _non_empty(project.get("name"))
    base_url = _non_empty(project.get("base_url"))
    description = _non_empty(project.get("description"))
    rows: list[tuple[str, str]] = []
    if name:
        rows.append(("Name", name))
    if base_url:
        rows.append(("Base URL", base_url))
    if description:
        rows.append(("Description", description))
    if not rows:
        return None
    return {"title": "项目信息", "rows": rows}


def build_context_info_block(context_info: dict[str, Any] | None) -> dict[str, Any] | None:
    """P1 · 「## 上下文信息」段：env_url / test_account / excluded / refs；任一非空即输出。"""
    if not isinstance(context_info, dict):
        return None
    rows: list[tuple[str, str]] = []
    for key, label in (
        ("env_url", "环境URL"),
        ("test_account", "测试账号"),
        ("excluded", "排除范围"),
        ("refs", "参考文档"),
    ):
        value = _non_empty(context_info.get(key))
        if value:
            rows.append((label, value))
    if not rows:
        return None
    return {"title": "上下文信息", "rows": rows}


def build_prompt_sections(blocks: list[dict[str, Any] | None]) -> list[dict[str, list[str]]]:
    """架构 §2 决策 3：分段函数。每段独立、空段整段丢弃。

    返回形如 [{"title": "项目信息", "rows": ["Name: ICM", ...]}, ...]，全空时返回 []。
    """
    sections: list[dict[str, list[str]]] = []
    for block in blocks or []:
        if not isinstance(block, dict):
            continue
        title = _non_empty(block.get("title"))
        raw_rows = block.get("rows") or []
        rendered: list[str] = []
        for row in raw_rows:
            if not isinstance(row, (tuple, list)) or len(row) != 2:
                continue
            k = _non_empty(row[0])
            v = _non_empty(row[1])
            if k and v:
                rendered.append(f"{k}: {v}")
        if not rendered:
            # 空段整段丢弃
            continue
        if title:
            sections.append({"title": title, "rows": rendered})
    return sections


def _last_prompt_text(sections: list[dict[str, list[str]]]) -> str:
    """把 sections 拼成可读 Markdown-ish 文本（调试 / 单测用）。空时返回 ''。"""
    if not sections:
        return ""
    parts: list[str] = []
    for sec in sections:
        title = _non_empty(sec.get("title")) or "段落"
        rows = sec.get("rows") or []
        parts.append(f"## {title}")
        for row in rows:
            parts.append(f"- {row}")
    return "\n".join(parts)


class AIService:
    """AI boundary for OpenAI-compatible chat completions."""

    provider = "minimax-m3"
    # 调试用：暴露最近一次 generate_cases_with_ai 的 prompt 完整 JSON 字符串
    # （基线 P0 验收："可通过 ai_service._last_prompt 调试看到"）
    _last_prompt: str = ""

    def generate_test_points(self, document: str, settings: dict[str, Any]) -> dict[str, Any]:
        if not document.strip():
            return {"test_points": [], "analysis_summary": "", "risk_summary": "", "case_count": 0}
        self._validate_settings(settings)
        provider = settings.get("provider", self.provider)
        payload = self._chat_completion_payload(settings["model"], document, provider)
        raw = self._post_json(
            self.chat_completions_url(settings["base_url"]),
            self.api_key_for_provider(settings),
            payload,
            timeout=self.request_timeout(provider),
        )
        return self.parse_chat_completion(raw)

    def test_connection(self, settings: dict[str, Any]) -> dict[str, str]:
        self._validate_settings(settings)
        provider = settings.get("provider", self.provider)
        payload = self._chat_completion_payload(settings["model"], '请只返回一个 JSON：{"ok": true}', provider)
        self._post_json(
            self.chat_completions_url(settings["base_url"]),
            self.api_key_for_provider(settings),
            payload,
            timeout=self.request_timeout(provider),
        )
        return {"status": "ok", "provider": settings.get("provider", self.provider), "model": settings["model"]}

    def list_ollama_models(self, base_url: str) -> dict[str, Any]:
        if not base_url.strip():
            raise AIConfigurationError("please configure Ollama base_url first")
        tags_url = self.ollama_tags_url(base_url)
        raw = self._get_json(tags_url)
        return {"base_url": base_url, "tags_url": tags_url, "models": self.parse_ollama_tags(raw)}

    def generate_cases(
        self,
        test_points: list[dict[str, Any]],
        template: str = "functional",
        title: str | None = None,
        settings: dict[str, Any] | None = None,
        generator: str = "rule",
        project: dict[str, Any] | None = None,
        context_info: dict[str, Any] | None = None,
    ) -> str:
        """P0 / P1 · 增量：接受 project / context_info，拼到 AI prompt 段（rule 模式不调 LLM 不受影响）。"""
        if generator == "ai":
            if settings is None:
                raise AIConfigurationError("请先配置模型后再使用 AI 生成用例")
            return self.generate_cases_with_ai(test_points, template, title, settings, project=project, context_info=context_info)
        return self.generate_cases_by_rule(test_points, template, title)

    def generate_cases_by_rule(self, test_points: list[dict[str, Any]], template: str = "functional", title: str | None = None) -> str:
        names = [str(point.get("name") or "未命名测试点") for point in test_points]
        case_title = title or case_title_for_template(template)
        case_type = case_type_for_template(template)
        source_ids = ", ".join(str(point.get("id")) for point in test_points if point.get("id") is not None)
        steps = "\n".join(f"  - {name}" for name in names)
        assertions = "\n".join(f"  - 验证：{name}" for name in names)
        return (
            "id: TC-ICM-DRAFT\n"
            f"title: {case_title}\n"
            "status: draft\n"
            f"type: {case_type}\n"
            f"source_test_points: [{source_ids}]\n"
            "preconditions:\n"
            "  - 已确认相关测试点\n"
            "  - 测试环境可访问\n"
            "steps:\n"
            f"{steps or '  - 待补充测试步骤'}\n"
            "expected_results:\n"
            f"{assertions or '  - 页面行为与业务目标一致'}\n"
            "automation_asset:\n"
            "  operation_steps: []\n"
            "  selectors: []\n"
            "  input_values: {}\n"
            "  assertions: []\n"
        )

    def generate_cases_with_ai(
        self,
        test_points: list[dict[str, Any]],
        template: str,
        title: str | None,
        settings: dict[str, Any],
        project: dict[str, Any] | None = None,
        context_info: dict[str, Any] | None = None,
    ) -> str:
        self._validate_settings(settings)
        provider = settings.get("provider", self.provider)
        payload = self._case_generation_payload(
            settings["model"],
            test_points,
            template,
            title,
            provider,
            project=project,
            context_info=context_info,
        )
        # 调试用：暴露最近一次完整 prompt（基线 P0 验收："可通过 ai_service._last_prompt 调试看到"）
        self._last_prompt = json.dumps(payload, ensure_ascii=False)
        raw = self._post_json(
            self.chat_completions_url(settings["base_url"]),
            self.api_key_for_provider(settings),
            payload,
            timeout=self.request_timeout(provider),
        )
        try:
            content = raw["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIProviderError("模型返回结构缺少 choices[0].message.content") from exc
        yaml_text = strip_markdown_fence(str(content)).strip()
        if not yaml_text or "steps:" not in yaml_text:
            raise AIProviderError("模型未返回有效的 YAML 用例草稿")
        return yaml_text

    def analyze_run_report(self, report: str, screenshots: list[Any], logs: list[str]) -> dict[str, object]:
        status = "failed" if "status: failed" in report.lower() else "passed"
        return {
            "provider": self.provider,
            "source": "rule",
            "status": status,
            "conclusion": "本次执行通过，报告、日志和截图证据已归档。" if status == "passed" else "本次执行失败，需要结合日志和失败截图复测。",
            "risks": ["关注页面加载等待信号，避免固定等待导致截图过早。"],
            "retest_suggestions": ["优先复跑失败 case；若失败重复出现，再固化 selector 或等待策略。"],
            "screenshot_count": len(screenshots),
            "log_count": len(logs),
        }

    def analyze_run_report_with_ai(self, report: str, screenshots: list[Any], logs: list[str], settings: dict[str, Any]) -> dict[str, object]:
        self._validate_settings(settings)
        provider = settings.get("provider", self.provider)
        payload = self._report_analysis_payload(settings["model"], report, screenshots, logs, provider)
        raw = self._post_json(
            self.chat_completions_url(settings["base_url"]),
            self.api_key_for_provider(settings),
            payload,
            timeout=self.request_timeout(provider),
        )
        try:
            content = raw["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIProviderError("model response missing choices[0].message.content") from exc
        data = parse_json_content(str(content))
        conclusion = first_text(data, "conclusion", "analysis", "current_analysis", "summary")
        risks = first_list(data, "risks", "risk_tips", "risk_summary", "risk")
        retest_suggestions = first_list(data, "retest_suggestions", "retest_advice", "suggestions", "recommendations")
        return {
            "provider": settings.get("provider", self.provider),
            "model": settings.get("model", ""),
            "source": "ai",
            "status": str(data.get("status") or ("failed" if "status: failed" in report.lower() else "passed")),
            "conclusion": conclusion,
            "risks": risks,
            "retest_suggestions": retest_suggestions,
            "screenshot_count": len(screenshots),
            "log_count": len(logs),
        }

    @staticmethod
    def parse_chat_completion(raw: dict[str, Any]) -> dict[str, Any]:
        try:
            content = raw["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIProviderError("模型返回结构缺少 choices[0].message.content") from exc

        data = parse_json_content(content)
        points = [
            TestPoint(
                name=str(item.get("name", "")).strip(),
                category=str(item.get("category", "功能")).strip() or "功能",
                priority=str(item.get("priority", "P1")).strip() or "P1",
                status=str(item.get("status", "待确认")).strip() or "待确认",
                description=str(item.get("description", "")).strip(),
            )
            for item in data.get("test_points", [])
            if str(item.get("name", "")).strip()
        ]
        return {
            "test_points": points,
            "analysis_summary": str(data.get("analysis_summary", "")).strip(),
            "risk_summary": str(data.get("risk_summary", "")).strip(),
            "case_count": int(data.get("case_count", len(points)) or len(points)),
        }

    def _validate_settings(self, settings: dict[str, Any]) -> None:
        provider = settings.get("provider", self.provider)
        if provider != "ollama-local" and not settings.get("api_key"):
            raise AIConfigurationError("请先在需求工作台保存模型 API Key")
        if not settings.get("base_url"):
            raise AIConfigurationError("请先配置模型 base_url")
        if not settings.get("model"):
            raise AIConfigurationError("请先配置模型 model")

    def _chat_completion_payload(self, model: str, document: str, provider: str = "minimax-m3") -> dict[str, Any]:
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是 ICM 自动化测试平台的测试分析助手。"
                        "请严格返回 JSON，不要输出 Markdown。"
                        "JSON 字段：test_points、analysis_summary、risk_summary、case_count。"
                        "test_points 每项字段：name、category、priority、status、description。"
                    ),
                },
                {
                    "role": "user",
                    "content": f"请从以下需求文档中生成测试点：\n{document}",
                },
            ],
            "temperature": 0.2,
            "stream": False,
        }
        if provider == "minimax-m3" or model == "MiniMax-M3":
            payload["thinking"] = {"type": "adaptive"}
            payload["max_completion_tokens"] = 8192
        else:
            payload["max_tokens"] = 8192
        return {key: value for key, value in payload.items() if value is not None}

    def _case_generation_payload(
        self,
        model: str,
        test_points: list[dict[str, Any]],
        template: str,
        title: str | None,
        provider: str = "minimax-m3",
        project: dict[str, Any] | None = None,
        context_info: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """P0 / P1 · 增量：项目信息 + 上下文信息按 _build_prompt_sections 拼到 user.message.content。"""
        extra_sections = build_prompt_sections(
            [
                build_project_block(project),
                build_context_info_block(context_info),
            ]
        )
        user_payload: dict[str, Any] = {
            "title": title or case_title_for_template(template),
            "template": template,
            "test_points": test_points,
        }
        if extra_sections:
            user_payload["prompt_sections"] = extra_sections
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是 ICM 自动化测试平台的测试用例设计助手。"
                        "只返回一个 YAML 文档，不要 Markdown 代码块。"
                        "YAML 必须包含 id、title、status、type、preconditions、steps、"
                        "expected_results、automation_asset。"
                        "automation_asset 必须包含 operation_steps、selectors、input_values、assertions。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(user_payload, ensure_ascii=False),
                },
            ],
            "temperature": 0.2,
            "stream": False,
        }
        if provider == "minimax-m3" or model == "MiniMax-M3":
            payload["thinking"] = {"type": "adaptive"}
            payload["max_completion_tokens"] = 8192
        else:
            payload["max_tokens"] = 8192
        return payload


    def _spec_generation_payload(
        self,
        model: str,
        document: str,
        standard_text: str,
        provider: str = 'minimax-m3',
        project: dict[str, Any] | None = None,
        context_info: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # P0 / P1 · 增量：项目信息 + 上下文信息按 build_prompt_sections 拼到 user.message.content.prompt_sections
        extra_sections = build_prompt_sections(
            [
                build_project_block(project),
                build_context_info_block(context_info),
            ]
        )
        standard_excerpt = standard_text[:3000]
        user_payload: dict[str, Any] = {
            'standard_excerpt': standard_excerpt,
            'output_limits': 'return valid JSON only, at most 12 concise cases, no Markdown, no trailing commas.',
            'requirement_document': document,
        }
        if extra_sections:
            user_payload['prompt_sections'] = extra_sections
        payload = {
            'model': model,
            'messages': [
                {
                    'role': 'system',
                    'content': 'You are a senior QA engineer. Generate test cases strictly following the 13-field standard supplied in the user message.\nOutput a single JSON object, no Markdown, no prose. Schema:\n{\n  "cases": [\n    {\n      "id": "MODULE_TYPE_NNN (e.g. LOGIN_FUN_001)",\n      "title": "one-line summary, object + action + condition",\n      "module": "feature module",\n      "priority": "P0|P1|P2|P3",\n      "type": "功能|异常|边界|权限|数据",\n      "precondition": "env, data, account, config",\n      "test_data": "concrete parameter list",\n      "steps": ["1. step one", "2. step two"],\n      "expected": ["1. element + state", "2. element + state"],\n      "requirement_id": "REQ-XXX (if known)",\n      "automation": "Yes|No|Planned",\n      "author": "AI",\n      "date": "YYYY-MM-DD",\n      "note": ""\n    }\n  ]\n}\nApply the 7 core principles: 1) 原子性 2) 独立性 3) 可重放 4) 可判定 5) 正反兼有 6) 面向业务 7) 词义一致.\nCover: normal flow + abnormal + boundary, one case = one check point.',
                },
                {
                    'role': 'user',
                    'content': json.dumps(user_payload, ensure_ascii=False),
                },
            ],
            'temperature': 0.2,
            'stream': False,
        }
        if provider == 'minimax-m3' or model == 'MiniMax-M3':
            payload['thinking'] = {'type': 'adaptive'}
            payload['max_completion_tokens'] = 4096
        else:
            payload['max_tokens'] = 12288
        if provider == 'ollama-local':
            payload['reasoning_effort'] = 'none'
        return {key: value for key, value in payload.items() if value is not None}

    def generate_test_cases_spec(
        self,
        document: str,
        standard_text: str,
        settings: dict[str, Any],
        project: dict[str, Any] | None = None,
        context_info: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not document.strip():
            return {'cases': [], 'raw': ''}
        self._validate_settings(settings)
        provider = settings.get('provider', self.provider)
        payload = self._spec_generation_payload(
            settings['model'],
            document,
            standard_text,
            provider,
            project=project,
            context_info=context_info,
        )
        raw = self._post_json(
            self.chat_completions_url(settings['base_url']),
            self.api_key_for_provider(settings),
            payload,
            timeout=max(self.request_timeout(provider), 900) if provider == 'ollama-local' else max(self.request_timeout(provider), 240),
        )
        # 调试用：暴露最近一次完整 prompt（与 generate_cases_with_ai 一致；P0-6 / P1-3 端到端可视）
        self._last_prompt = json.dumps(payload, ensure_ascii=False)
        try:
            message = raw['choices'][0]['message']
        except (KeyError, IndexError, TypeError) as exc:
            raise AIProviderError('model did not return a chat completion') from exc
        content = self._message_text(message.get('content'))
        if not content:
            content = self._message_text(message.get('reasoning'))
        return {'cases': self._parse_spec_cases(content), 'raw': content}

    @staticmethod
    def _message_text(value: Any) -> str:
        if value is None:
            return ''
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            chunks = [AIService._message_text(item) for item in value]
            return "\n".join(chunk for chunk in chunks if chunk).strip()
        if isinstance(value, dict):
            for key in ('text', 'content', 'reasoning', 'output_text'):
                text = AIService._message_text(value.get(key))
                if text:
                    return text
            return ''
        return str(value).strip()

    @staticmethod
    def _parse_spec_cases(content: str) -> list[dict[str, Any]]:
        text = strip_think_blocks(content)
        text = strip_markdown_fence(text)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = AIService._parse_json_fragment(text)
        if not ((isinstance(data, dict) and 'cases' in data) or isinstance(data, list)):
            for candidate in _json_fragments(text):
                try:
                    fragment = json.loads(candidate)
                except json.JSONDecodeError:
                    continue
                if (isinstance(fragment, dict) and 'cases' in fragment) or isinstance(fragment, list):
                    data = fragment
                    break
        if isinstance(data, dict) and 'cases' in data:
            cases = data['cases']
        elif isinstance(data, list):
            cases = data
        else:
            raise AIProviderError('model returned unexpected JSON shape')
        if not isinstance(cases, list):
            raise AIProviderError('model did not return a list of cases')
        return [case for case in cases if isinstance(case, dict)]

    @staticmethod
    def _parse_json_fragment(text: str) -> Any:
        text = strip_think_blocks(text)
        for candidate in _json_fragments(text):
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
        raise AIProviderError('模型输出格式异常')

    def _report_analysis_payload(self, model: str, report: str, screenshots: list[Any], logs: list[str], provider: str = "minimax-m3") -> dict[str, Any]:
        screenshot_summary = [
            {
                "filename": item.get("filename") if isinstance(item, dict) else str(item),
                "case_id": item.get("case_id") if isinstance(item, dict) else "",
                "path": item.get("path") if isinstance(item, dict) else "",
            }
            for item in screenshots[:12]
        ]
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an ICM automation test report analyst. Return strict JSON only. "
                        "JSON fields: status, conclusion, risks, retest_suggestions. "
                        "risks and retest_suggestions must be arrays of short Chinese strings. "
                        "Focus on failure cause, missing evidence, unstable waits, selector risk, and retest advice."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "markdown_report": report[:12000],
                            "screenshots": screenshot_summary,
                            "logs": logs[-120:],
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "temperature": 0.2,
            "stream": False,
        }
        if provider == "minimax-m3" or model == "MiniMax-M3":
            payload["thinking"] = {"type": "adaptive"}
            payload["max_completion_tokens"] = 4096
        else:
            payload["max_tokens"] = 4096
        return payload

    @staticmethod
    def chat_completions_url(base_url: str) -> str:
        normalized = base_url.strip().rstrip("/")
        if normalized.endswith("/chat/completions"):
            return normalized
        return f"{normalized}/chat/completions"

    @staticmethod
    def ollama_tags_url(base_url: str) -> str:
        normalized = base_url.strip().rstrip("/")
        parts = urlsplit(normalized)
        path = parts.path.rstrip("/")
        for suffix in ("/v1/chat/completions", "/chat/completions", "/v1"):
            if path.endswith(suffix):
                path = path[: -len(suffix)]
                break
        return urlunsplit((parts.scheme, parts.netloc, f"{path}/api/tags", "", ""))

    @staticmethod
    def parse_ollama_tags(raw: dict[str, Any]) -> list[dict[str, Any]]:
        models = raw.get("models", [])
        if not isinstance(models, list):
            raise AIProviderError("Ollama tags response missing models list")
        return [
            {
                "name": str(item.get("name") or item.get("model") or "").strip(),
                "model": str(item.get("model") or item.get("name") or "").strip(),
                "modified_at": item.get("modified_at"),
                "size": item.get("size"),
                "digest": item.get("digest"),
                "details": item.get("details") if isinstance(item.get("details"), dict) else {},
            }
            for item in models
            if isinstance(item, dict) and str(item.get("name") or item.get("model") or "").strip()
        ]

    @staticmethod
    def request_timeout(provider: str) -> int:
        return 300 if provider == "ollama-local" else 60

    def _get_json(self, url: str) -> dict[str, Any]:
        request = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise AIProviderError(f"Ollama models request failed: HTTP {exc.code} {detail}") from exc
        except urllib.error.URLError as exc:
            raise AIProviderError(f"Ollama models network failed: {exc.reason}") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise AIProviderError("Ollama models request timed out after 15 seconds") from exc
        except json.JSONDecodeError as exc:
            raise AIProviderError("Ollama tags response is not valid JSON") from exc

    def _post_json(self, url: str, api_key: str, payload: dict[str, Any], timeout: int = 60) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=self.request_headers(api_key),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (TimeoutError, socket.timeout) as exc:
            raise AIProviderError(f"model request timed out after {timeout} seconds") from exc
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise AIProviderError(f"模型调用失败：HTTP {exc.code} {detail}") from exc
        except urllib.error.URLError as exc:
            raise AIProviderError(f"模型网络连接失败：{exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise AIProviderError("模型返回不是合法 JSON") from exc

    @staticmethod
    def request_headers(api_key: str) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    @staticmethod
    def api_key_for_provider(settings: dict[str, Any]) -> str:
        if settings.get("provider") == "ollama-local":
            return ""
        return settings.get("api_key", "")


def parse_json_content(content: str) -> dict[str, Any]:
    text = strip_think_blocks(content.strip())
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise AIProviderError("模型内容不是 JSON 对象")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise AIProviderError("模型内容 JSON 解析失败") from exc


_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)


def strip_think_blocks(content: str) -> str:
    """剥除 LLM 推理模型在 JSON 之前输出的 <think>...</think> 思考块。"""
    if not content:
        return content
    return _THINK_BLOCK_RE.sub("", content).strip()


def strip_markdown_fence(content: str) -> str:
    text = content.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _json_fragments(text: str) -> list[str]:
    fragments: list[str] = []
    stack: list[str] = []
    start_index = -1
    in_string = False
    escaped = False
    quote_char = ""
    pairs = {"{": "}", "[": "]"}

    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == quote_char:
                in_string = False
            continue

        if char in {'"', "'"}:
            in_string = True
            quote_char = char
            continue

        if char in pairs:
            if not stack:
                start_index = index
            stack.append(pairs[char])
            continue

        if stack and char == stack[-1]:
            stack.pop()
            if not stack and start_index >= 0:
                fragments.append(text[start_index : index + 1])
                start_index = -1
    return fragments


def normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def first_text(data: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def first_list(data: dict[str, Any], *keys: str) -> list[str]:
    for key in keys:
        items = normalize_string_list(data.get(key))
        if items:
            return items
    return []


def case_title_for_template(template: str) -> str:
    return {
        "functional": "AI 生成-功能用例草稿",
        "negative": "AI 生成-异常用例草稿",
        "regression": "AI 生成-回归用例草稿",
        "e2e": "AI 生成-端到端链路草稿",
    }.get(template, "AI 生成用例草稿")


def case_type_for_template(template: str) -> str:
    return {
        "functional": "功能用例",
        "negative": "异常用例",
        "regression": "回归用例",
        "e2e": "端到端链路",
    }.get(template, "功能用例")
