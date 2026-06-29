from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

from runner.agent_codegen import generate_candidate_flow
from runner.case_expectations import case_expected_results
from runner.agent_stage_router import build_stage_goal, execute_stage_strategy, normalize_stage_history, now_iso, plan_agent_execution, stage_view
from runner.browser import attach_case_runtime, ensure_logged_out, first_visible, load_case, load_case_file, load_system, open_login_page, screenshot
from runner.evidence_recorder import attach_evidence_recorder, evidence_summary


ROOT = Path(__file__).resolve().parents[1]
AGENT_REPORT_ROOT = ROOT / "reports" / "agent-explore"


def allowed_hosts_for_system(system: dict[str, Any]) -> set[str]:
    hosts: set[str] = set()
    for key in ("base_url", "entry_url", "login_url"):
        value = str(system.get(key) or "").strip()
        if not value:
            continue
        parsed = urlparse(value)
        if parsed.hostname:
            hosts.add(parsed.hostname)
    return hosts


def build_agent_goal(case: dict[str, Any]) -> str:
    lines = [
        f"Case ID: {case.get('id', '')}",
        f"Title: {case.get('title', '')}",
    ]
    precondition = str(case.get("precondition") or "").strip()
    if precondition:
        lines.append(f"Precondition: {precondition}")

    test_data = case.get("test_data")
    if isinstance(test_data, str) and test_data.strip():
        lines.append(f"Test data: {test_data.strip()}")
    elif isinstance(test_data, dict) and test_data:
        lines.append("Test data:")
        lines.extend(f"- {key}={value}" for key, value in test_data.items())

    lines.append("Steps:")
    lines.extend(f"- {step}" for step in case.get("steps") or [])
    lines.append("Expected results:")
    lines.extend(f"- {item}" for item in case_expected_results(case))

    asset = case.get("automation_asset") or {}
    operation_steps = asset.get("operation_steps") or []
    if operation_steps:
        lines.append("Automation operation steps:")
        lines.extend(f"- {step}" for step in operation_steps)

    assertions = asset.get("assertions") or []
    if assertions:
        lines.append("Assertions:")
        lines.extend(f"- {item}" for item in assertions)

    return "\n".join(line for line in lines if line is not None)


def build_self_heal_goal(case: dict[str, Any], healing_context: dict[str, Any]) -> str:
    """Build goal text for a self-heal retry. Adds structured diagnosis, recovery strategy, and stop conditions on top of build_agent_goal."""
    base_goal = build_agent_goal(case)
    ctx = healing_context or {}
    diagnosis = ctx.get("diagnosis") or {}
    if not diagnosis:
        diagnosis = {"category": "unknown", "evidence": str(ctx.get("failure_summary") or "(no diagnosis provided)").strip()}
    lines = [base_goal, "", "Self-heal context:"]
    failure_summary = str(ctx.get("failure_summary") or "").strip()
    healing_hint = str(ctx.get("healing_hint") or "").strip()
    if failure_summary:
        lines.append(f"- Previous failure: {failure_summary}")
    if healing_hint:
        lines.append(f"- Healing hint: {healing_hint}")
    attempt_index = int(ctx.get("attempt_index") or 1)
    max_attempts = int(ctx.get("max_attempts") or 3)
    lines.append("")
    lines.append("失败诊断：")
    lines.append(f"- Category: {diagnosis.get('category', 'unknown')}")
    lines.append(f"- 证据: {diagnosis.get('evidence', '')}")
    lines.append(f"- 重试次数: {attempt_index}/{max_attempts}")
    lines.append("")
    lines.append("恢复策略（按 Category 选一条）：")
    lines.append("- locator_drift（定位漂移）：重新观察页面，按邻近 label 文本或 placeholder 选新 ref；不要复用之前的 ref。")
    lines.append("- timing（时序问题）：等待 1-3 秒后再 assert 或 click；弹窗/路由切换后不要立即操作，先等 DOM 稳定。")
    lines.append("- logic_understanding（业务理解偏差）：重读用例步骤和预期结果；不要在不理解业务的情况下继续操作。")
    lines.append("- unrecoverable（不可恢复）：不要重试，立刻 finish，reason 写明 'unrecoverable: <具体原因>'。")
    lines.append("")
    lines.append("停止条件（任一命中立刻 finish）：")
    lines.append(f"- 已是第 {max_attempts} 次重试。")
    lines.append("- 页面 visibleText 已包含任意一条 Expected results。")
    lines.append("- 失败信号与上一轮 Category 相同。")
    lines.append("- 剩余工作无法仅靠浏览器操作完成（需后端/账号/数据准备）。")
    last_steps = ctx.get("last_history") or []
    if last_steps:
        lines.append("")
        lines.append("Recent failing tail:")
        for item in last_steps:
            if not isinstance(item, dict):
                continue
            decision = item.get("decision") if isinstance(item.get("decision"), dict) else {}
            execution = item.get("execution") if isinstance(item.get("execution"), dict) else {}
            lines.append(
                f"- step={item.get('step')} action={decision.get('action')} ref={decision.get('ref')} reason={decision.get('reason')} result={execution.get('result') or execution.get('error')}"
            )
    return "\n".join(lines)
async def observe_page(page) -> dict[str, Any]:
    return await page.evaluate(OBSERVE_PAGE_SCRIPT)


OBSERVE_PAGE_SCRIPT = """() => {
          const visible = (el) => {
            let current = el;
            while (current && current.nodeType === Node.ELEMENT_NODE) {
              const style = window.getComputedStyle(current);
              if (style.visibility === 'hidden' || style.display === 'none' || style.opacity === '0') {
                return false;
              }
              current = current.parentElement;
            }
            const rect = el.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
          };
          const esc = (value) => window.CSS && CSS.escape
            ? CSS.escape(value)
            : String(value).replace(/["\\\\#.;?+*~':!^$[\\]()=>|/@]/g, "\\\\$&");
          const selectorFor = (el) => {
            const anchor = el.closest('a[href]');
            if (anchor) {
              const href = anchor.getAttribute('href');
              if (href) return `a[href="${esc(href)}"]`;
            }
            if (el.id) return `#${esc(el.id)}`;
            const testId = el.getAttribute('data-testid') || el.getAttribute('data-test');
            if (testId) return `[data-testid="${esc(testId)}"],[data-test="${esc(testId)}"]`;
            const name = el.getAttribute('name');
            if (name) return `${el.tagName.toLowerCase()}[name="${esc(name)}"]`;
            const placeholder = el.getAttribute('placeholder');
            if (placeholder) return `${el.tagName.toLowerCase()}[placeholder="${esc(placeholder)}"]`;

            const parts = [];
            let current = el;
            while (current && current.nodeType === Node.ELEMENT_NODE && current !== document.body && parts.length < 5) {
              const tag = current.tagName.toLowerCase();
              const parent = current.parentElement;
              if (!parent) break;
              const siblings = Array.from(parent.children).filter((child) => child.tagName === current.tagName);
              const index = siblings.indexOf(current) + 1;
              parts.unshift(siblings.length > 1 ? `${tag}:nth-of-type(${index})` : tag);
              current = parent;
            }
            return parts.join(' > ') || el.tagName.toLowerCase();
          };
          const normalizeText = (value) =>
            String(value || '')
              .replace(/\\s+/g, ' ')
              .trim();
          const uniqueTexts = (items) => {
            const seen = new Set();
            const result = [];
            for (const item of items) {
              const normalized = normalizeText(item);
              if (!normalized || seen.has(normalized)) continue;
              seen.add(normalized);
              result.push(normalized);
            }
            return result;
          };
          const textOf = (el) => {
            const descendants = Array.from(el.querySelectorAll('span,[title],svg + span'))
              .map((node) => node.textContent || node.getAttribute('title') || '');
            const closestMenu = el.closest('.el-submenu__title,.el-menu-item,[role="menuitem"],a,li');
            const href = el.getAttribute('href') || (closestMenu && closestMenu.getAttribute && closestMenu.getAttribute('href')) || '';
            const hrefLabel = href.startsWith('#/')
              ? href.slice(2).replace(/[/?#_-]+/g, ' ')
              : href;
            return uniqueTexts([
              el.innerText,
              el.textContent,
              el.value,
              el.getAttribute('aria-label'),
              el.getAttribute('title'),
              el.getAttribute('placeholder'),
              el.getAttribute('alt'),
              descendants.join(' '),
              closestMenu && (closestMenu.innerText || closestMenu.textContent || closestMenu.getAttribute('title')),
              hrefLabel,
            ])
              .join(' | ')
              .slice(0, 160);
          };
          const interactives = Array.from(
            document.querySelectorAll(
              'a,button,input,textarea,select,[role="button"],[role="link"],[role="menuitem"],[contenteditable="true"],.el-submenu__title,.el-menu-item'
            )
          )
            .filter(visible)
            .slice(0, 45)
            .map((el, index) => ({
              ref: `e${index + 1}`,
              tag: el.tagName.toLowerCase(),
              role: el.getAttribute('role') || '',
              type: el.getAttribute('type') || '',
              text: textOf(el),
              ariaLabel: el.getAttribute('aria-label') || '',
              placeholder: el.getAttribute('placeholder') || '',
              selector: selectorFor(el),
            }));
          const visibleText = (document.body && document.body.innerText || '')
            .split(/\\n+/)
            .map((line) => line.replace(/\\s+/g, ' ').trim())
            .filter(Boolean)
            .slice(0, 35);
          return { url: location.href, title: document.title, visibleText, interactives };
        }"""


async def run_agent_loop(
    goal: str,
    observe: Callable[[], Awaitable[dict[str, Any]]],
    decide: Callable[[str, dict[str, Any], list[dict[str, Any]], int, int], Awaitable[dict[str, Any]]],
    execute: Callable[[Any, dict[str, Any]], Awaitable[dict[str, Any]] | dict[str, Any] | None],
    allowed_hosts: set[str],
    max_steps: int = 25,
) -> dict[str, Any]:
    from runner.agent_actions import normalize_decision, validate_decision

    history: list[dict[str, Any]] = []
    for step_index in range(max_steps):
        observation = await observe()
        try:
            raw_decision = await decide(goal, observation, history, step_index, max_steps)
        except Exception as exc:
            history.append(
                {
                    "step": step_index + 1,
                    "decision": {
                        "action": "fail",
                        "ref": "",
                        "url": "",
                        "value": "",
                        "key": "",
                        "reason": str(exc),
                    },
                    "observation": observation,
                    "execution": {"result": "error", "error": str(exc)},
                }
            )
            return {"ok": False, "status": "failed", "goal": goal, "history": history, "error": str(exc)}
        decision = normalize_decision(raw_decision)
        decision_dict = {
            "action": decision.action,
            "ref": decision.ref,
            "url": decision.url,
            "value": decision.value,
            "key": decision.key,
            "reason": decision.reason,
        }
        if decision.action == "finish":
            if _should_continue_after_login_satisfied(goal, observation, history, decision.reason):
                history.append(
                    {
                        "step": step_index + 1,
                        "decision": {
                            "action": "wait",
                            "ref": "",
                            "url": "",
                            "value": "",
                            "key": "",
                            "reason": "login precondition already satisfied; finish ignored until business steps are complete",
                        },
                        "observation": observation,
                        "execution": {"result": "login_precondition_satisfied"},
                    }
                )
                continue
            history.append({"step": step_index + 1, "decision": decision_dict, "observation": observation})
            return {"ok": True, "status": "passed", "goal": goal, "history": history, "summary": decision.reason}
        if decision.action == "fail":
            if _should_continue_after_login_satisfied(goal, observation, history, decision.reason):
                history.append(
                    {
                        "step": step_index + 1,
                        "decision": {
                            "action": "wait",
                            "ref": "",
                            "url": "",
                            "value": "",
                            "key": "",
                            "reason": "login precondition already satisfied; continue with next business step",
                        },
                        "observation": observation,
                        "execution": {"result": "login_precondition_satisfied"},
                    }
                )
                continue
            history.append({"step": step_index + 1, "decision": decision_dict, "observation": observation})
            return {"ok": False, "status": "failed", "goal": goal, "history": history, "error": decision.reason}

        observed_refs = {item.get("ref", "") for item in observation.get("interactives") or []}
        errors = validate_decision(decision, observed_refs=observed_refs, allowed_hosts=allowed_hosts)
        if errors and _should_finish_on_success_signal(goal, observation, history, decision, errors):
            history.append(
                {
                    "step": step_index + 1,
                    "decision": {
                        "action": "finish",
                        "ref": "",
                        "url": "",
                        "value": "",
                        "key": "",
                        "reason": "success signal observed; ignored trailing empty-ref action",
                    },
                    "observation": observation,
                    "execution": {"result": "finished_on_success_signal"},
                }
            )
            return {
                "ok": True,
                "status": "passed",
                "goal": goal,
                "history": history,
                "summary": "success signal observed; ignored trailing empty-ref action",
            }
        if errors:
            history.append(
                {
                    "step": step_index + 1,
                    "decision": decision_dict,
                    "observation": observation,
                    "execution": {"result": "error", "error": "; ".join(errors)},
                }
            )
            return {"ok": False, "status": "failed", "goal": goal, "history": history, "error": "; ".join(errors)}

        previous = history[-1] if history else {}
        previous_decision = previous.get("decision") or {}
        same_action = (
            previous_decision.get("action"),
            previous_decision.get("ref"),
            previous_decision.get("url"),
            previous_decision.get("value"),
            previous_decision.get("key"),
        ) == (decision.action, decision.ref, decision.url, decision.value, decision.key)
        if same_action and previous.get("observation") == observation:
            history.append(
                {
                    "step": step_index + 1,
                    "decision": decision_dict,
                    "observation": observation,
                    "execution": {
                        "result": "duplicate_action_blocked",
                        "error": "The same action was already executed without any page-state change; choose a different action.",
                    },
                }
            )
            continue

        maybe_execution = execute(decision, observation)
        execution = await maybe_execution if hasattr(maybe_execution, "__await__") else maybe_execution
        if isinstance(execution, dict) and execution.get("result") == "error":
            history.append(
                {
                    "step": step_index + 1,
                    "decision": decision_dict,
                    "observation": observation,
                    "execution": execution,
                }
            )
            return {
                "ok": False,
                "status": "failed",
                "goal": goal,
                "history": history,
                "error": str(execution.get("error") or "agent action failed"),
            }
        history.append(
            {
                "step": step_index + 1,
                "decision": decision_dict,
                "observation": observation,
                "execution": execution or {"result": "ok"},
            }
        )

    return {
        "ok": False,
        "status": "failed",
        "goal": goal,
        "history": history,
        "error": f"Agent reached max steps ({max_steps}).",
    }


async def run_generic_stage_loop(
    page,
    stage_goal: str,
    allowed_hosts: set[str],
    *,
    max_steps: int = 12,
) -> dict[str, Any]:
    async def observe() -> dict[str, Any]:
        return await observe_page(page)

    async def decide(goal_text: str, observation: dict[str, Any], history: list[dict[str, Any]], step_index: int, loop_max_steps: int) -> dict[str, Any]:
        return await decide_next_action(goal_text, observation, history, step_index, loop_max_steps)

    async def execute(decision, observation: dict[str, Any]) -> dict[str, Any]:
        try:
            result = await execute_agent_decision(page, decision, observation)
        except Exception as exc:
            return {"result": "error", "action": decision.action, "ref": decision.ref, "error": str(exc)}
        run_id = getattr(page, "_case_run_id", "")
        case_id = getattr(page, "_case_id", "")
        if run_id and case_id:
            screenshot_index = int(getattr(page, "_agent_step_screenshot_index", 0)) + 1
            setattr(page, "_agent_step_screenshot_index", screenshot_index)
            screenshot_name = f"agent-step-{screenshot_index:02d}.png"
            await screenshot(page, run_id, case_id, screenshot_name)
            result = {**result, "screenshot_name": screenshot_name}
        return result

    return await run_agent_loop(
        goal=stage_goal,
        observe=observe,
        decide=decide,
        execute=execute,
        allowed_hosts=allowed_hosts,
        max_steps=max_steps,
    )


def _goal_username(goal: str, history: list[dict[str, Any]]) -> str:
    match = re.search(r"username\s*[:=]\s*([A-Za-z0-9_.@-]+)", goal, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    for item in history:
        decision = item.get("decision") or {}
        value = str(decision.get("value") or "").strip()
        reason = str(decision.get("reason") or "").lower()
        if value and "username" in reason:
            return value
    return ""


def _observation_indicates_logged_in(goal: str, observation: dict[str, Any], history: list[dict[str, Any]]) -> bool:
    url = str(observation.get("url") or "").lower()
    if "login" in url:
        return False
    goal_text = goal.lower()
    if "登录" not in goal and "login" not in goal_text:
        return False
    username = _goal_username(goal, history)
    visible = " ".join(str(item) for item in observation.get("visibleText") or [])
    interactives = " ".join(str(item.get("text") or "") for item in observation.get("interactives") or [])
    haystack = f"{visible} {interactives}"
    return bool(username) and username in haystack


def _observation_is_authenticated_context(goal: str, observation: dict[str, Any]) -> bool:
    url = str(observation.get("url") or "").lower()
    if not url or "login" in url:
        return False
    goal_text = goal.lower()
    return "login" in goal_text or "鐧诲綍" in goal


def _should_continue_after_login_satisfied(goal: str, observation: dict[str, Any], history: list[dict[str, Any]], reason: str) -> bool:
    if any((item.get("execution") or {}).get("result") == "login_precondition_satisfied" for item in history):
        return False
    if not _observation_is_authenticated_context(goal, observation):
        return False
    normalized_reason = reason.lower()
    markers = ("already on home", "login already", "login form is not visible", "login step was skipped", "pre-existing session", "auto-login")
    return any(marker in normalized_reason for marker in markers)


def _should_finish_on_success_signal(
    goal: str,
    observation: dict[str, Any],
    history: list[dict[str, Any]],
    decision: Any,
    errors: list[str],
) -> bool:
    if not errors or not any(error.startswith("unknown ref: empty") for error in errors):
        return False
    if str(getattr(decision, "action", "")) not in {"click", "fill", "press"}:
        return False
    return _observation_indicates_logged_in(goal, observation, history)


def build_agent_prompt(goal: str, observation: dict[str, Any], history: list[dict[str, Any]], step_index: int, max_steps: int) -> str:
    compact_history = [
        {
            "step": item.get("step"),
            "action": (item.get("decision") or {}).get("action"),
            "ref": (item.get("decision") or {}).get("ref"),
            "value": (item.get("decision") or {}).get("value"),
            "result": (item.get("execution") or {}).get("result") or (item.get("execution") or {}).get("error"),
        }
        for item in history[-6:]
    ]
    return (
        "You are a bounded browser automation Agent for ICM regression exploration.\n"
        "Return exactly one JSON object. Do not return Markdown or explanations.\n\n"
        f"Goal:\n{goal}\n\n"
        f"Step: {step_index + 1}/{max_steps}\n\n"
        "Allowed actions: goto, fill, click, press, wait, scroll, assert_text, finish, fail.\n"
        "Safety rules:\n"
        "1. click/fill/press must use a ref from observation.interactives.\n"
        "2. Do not invent selectors.\n"
        "3. Use credentials and other input values from the case goal exactly when they are provided.\n"
        "4. Do not substitute default admin/test accounts unless the case goal explicitly says so.\n"
        "5. Do not delete data, make payments, send messages, or download files.\n"
        "6. If the current URL is already outside the login page and the goal includes a login step, treat login as already satisfied and continue with the next business step. Never finish only because login is satisfied when later business steps exist.\n"
        "7. If the goal is complete, return {\"action\":\"finish\",\"reason\":\"...\"}.\n"
        "8. If blocked, return {\"action\":\"fail\",\"reason\":\"...\"}.\n\n"
        "Examples:\n"
        "{\"action\":\"fill\",\"ref\":\"e1\",\"value\":\"test\",\"reason\":\"fill username from case test data\"}\n"
        "{\"action\":\"fill\",\"ref\":\"e2\",\"value\":\"123456\",\"reason\":\"fill password from case test data\"}\n"
        "{\"action\":\"click\",\"ref\":\"e2\",\"reason\":\"submit form\"}\n"
        "{\"action\":\"assert_text\",\"value\":\"Home\",\"reason\":\"verify homepage\"}\n\n"
        f"Recent history:\n{json.dumps(compact_history, ensure_ascii=False, indent=2)}\n\n"
        f"Current observation:\n{json.dumps(observation, ensure_ascii=False, indent=2)}"
    )


_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)


def _clean_agent_json_text(text: str) -> str:
    cleaned = _THINK_BLOCK_RE.sub("", text.strip()).strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return cleaned


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = _clean_agent_json_text(text)
    if not cleaned:
        raise ValueError("AI response JSON parse failed: empty content after cleanup")
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            excerpt = cleaned[:160].replace("\n", "\\n")
            raise ValueError(f"AI response JSON parse failed: {exc}; excerpt={excerpt}") from exc
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError as fragment_exc:
            excerpt = match.group(0)[:160].replace("\n", "\\n")
            raise ValueError(f"AI response JSON parse failed: {fragment_exc}; excerpt={excerpt}") from fragment_exc
    if not isinstance(parsed, dict):
        raise ValueError("AI response JSON must be an object")
    return parsed


def _agent_decision_payload(model: str, provider: str, prompt: str, parse_error: str = "") -> dict[str, Any]:
    user_prompt = prompt
    if parse_error:
        user_prompt = (
            f"{prompt}\n\n"
            "The previous response was invalid JSON and could not be parsed.\n"
            f"Parser error: {parse_error}\n"
            "Return only one complete JSON object now, with no Markdown and no trailing prose."
        )
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are a bounded browser automation Agent. Return exactly one valid JSON object.",
            },
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "stream": False,
    }
    if provider == "minimax-m3" or model == "MiniMax-M3":
        payload["thinking"] = {"type": "disabled"}
        payload["max_completion_tokens"] = 1200
    else:
        payload["max_tokens"] = 1200
    return payload


def _chat_content(payload: dict[str, Any]) -> str:
    choice = (payload.get("choices") or [{}])[0]
    content = ((choice.get("message") or {}).get("content") or choice.get("text") or payload.get("reply") or "").strip()
    if content:
        return content
    raise ValueError(f"AI response has no message content: {json.dumps(payload, ensure_ascii=False)[:500]}")


def _target_text_candidates(target: dict[str, Any]) -> list[str]:
    text = str(target.get("text") or "").strip()
    if not text:
        return []
    candidates: list[str] = []
    for part in text.split("|"):
        normalized = " ".join(part.split()).strip()
        if normalized and normalized not in candidates:
            candidates.append(normalized)
    return candidates


def _target_selector_candidates(target: dict[str, Any], action: str) -> list[str]:
    selector = str(target.get("selector") or "").strip()
    candidates = [selector] if selector else []
    if action == "click":
        candidates.extend(f"text={text}" for text in _target_text_candidates(target))
    deduped: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in deduped:
            deduped.append(candidate)
    return deduped


async def decide_next_action(goal: str, observation: dict[str, Any], history: list[dict[str, Any]], step_index: int, max_steps: int) -> dict[str, Any]:
    from icm_platform.ai_service import AIConfigurationError, AIService
    from icm_platform.db import get_ai_settings

    settings = get_ai_settings(mask_key=False)
    if not settings.get("api_key") or not settings.get("base_url") or not settings.get("model"):
        raise AIConfigurationError("Agent Explore requires configured AI provider, base_url, model, and api_key.")

    service = AIService()
    provider = settings.get("provider", service.provider)
    prompt = build_agent_prompt(goal, observation, history, step_index, max_steps)
    parse_error = ""
    for attempt in range(2):
        payload = _agent_decision_payload(settings["model"], provider, prompt, parse_error)
        raw = service._post_json(
            service.chat_completions_url(settings["base_url"]),
            service.api_key_for_provider(settings),
            payload,
            timeout=service.request_timeout(provider),
        )
        try:
            return extract_json_object(_chat_content(raw))
        except ValueError as exc:
            parse_error = str(exc)
            if attempt == 1:
                raise ValueError(f"AI 决策返回的 JSON 不完整或格式错误，请重新执行本用例。原始错误：{parse_error}") from exc
    raise ValueError(f"AI 决策返回的 JSON 不完整或格式错误，请重新执行本用例。原始错误：{parse_error}")


async def execute_agent_decision(page, decision, observation: dict[str, Any]) -> dict[str, Any]:
    if decision.action == "goto":
        await page.goto(decision.url, wait_until="domcontentloaded", timeout=15000)
        return {"result": "navigated", "url": page.url}
    if decision.action == "wait":
        await page.wait_for_timeout(1200)
        return {"result": "waited"}
    if decision.action == "scroll":
        await page.mouse.wheel(0, int(decision.value or 650))
        return {"result": "scrolled"}
    if decision.action == "assert_text":
        text = await page.locator("body").inner_text(timeout=5000)
        if decision.value not in text:
            raise RuntimeError(f"assert_text failed: {decision.value}")
        return {"result": "asserted_text", "value": decision.value}

    target = next((item for item in observation.get("interactives") or [] if item.get("ref") == decision.ref), None)
    if decision.action == "press" and not target and not decision.ref:
        await page.keyboard.press(decision.key or "Enter")
        return {"result": "pressed", "ref": "", "key": decision.key or "Enter", "selector": ""}
    if not target:
        raise RuntimeError(f"Agent selected unknown ref: {decision.ref}")
    selector_candidates = _target_selector_candidates(target, decision.action)
    locator = await first_visible(page, selector_candidates)
    if locator is None:
        raise RuntimeError(f"Agent target is not visible: {selector_candidates}")
    selector = selector_candidates[0] if selector_candidates else ""
    if decision.action == "fill":
        await locator.fill(decision.value, timeout=8000)
        return {"result": "filled", "ref": decision.ref, "selector": selector}
    if decision.action == "click":
        await locator.click(timeout=8000)
        return {"result": "clicked", "ref": decision.ref, "selector": selector}
    if decision.action == "press":
        await locator.press(decision.key or "Enter", timeout=8000)
        return {"result": "pressed", "ref": decision.ref, "key": decision.key or "Enter", "selector": selector}
    raise RuntimeError(f"Unsupported agent action: {decision.action}")


def _load_case_arg(case_arg: str) -> dict[str, Any]:
    path = Path(case_arg)
    if path.exists():
        return load_case_file(path)
    return load_case(case_arg)


def _write_trace_artifacts(run_id: str, trace: dict[str, Any], case: dict[str, Any] | None = None) -> dict[str, str]:
    out_dir = AGENT_REPORT_ROOT / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    trace_path = out_dir / "trace.json"
    trace_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
    paths = {"trace_path": str(trace_path.relative_to(ROOT))}
    if trace.get("ok"):
        candidate_path = out_dir / "candidate_flow.py"
        candidate_path.write_text(generate_candidate_flow(trace, case), encoding="utf-8")
        paths["candidate_flow_path"] = str(candidate_path.relative_to(ROOT))
    return paths


def _write_trace_snapshot(run_id: str, trace: dict[str, Any]) -> None:
    out_dir = AGENT_REPORT_ROOT / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    trace_path = out_dir / "trace.json"
    trace_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")


def _finalize_stage_runs(trace: dict[str, Any], *, current_stage_id: str = "", current_stage_name: str = "", current_strategy: str = "") -> dict[str, Any]:
    trace["current_stage_id"] = current_stage_id
    trace["current_stage_name"] = current_stage_name
    trace["current_strategy"] = current_strategy
    return trace


def _load_healing_context(run_id: str) -> dict[str, Any] | None:
    path = ROOT / "reports" / "draft-runs" / run_id / "healing-context.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


async def run_agent_explore(page, run_id: str, case_arg: str) -> dict[str, Any]:
    case = _load_case_arg(case_arg)
    system = load_system(case["system"])
    case_id = str(case.get("id") or case_arg)
    allowed_hosts = allowed_hosts_for_system(system)
    if not allowed_hosts:
        return {"status": "failed", "run_id": run_id, "case_id": case_id, "error": "No allowed ICM hosts configured."}

    evidence = attach_evidence_recorder(page, run_id, case_id)
    await evidence.start(page)
    attach_case_runtime(page, run_id, case_id)
    await ensure_logged_out(page, system)
    await open_login_page(page, system)
    await screenshot(page, run_id, case_id, "01-entry.png")
    healing_context = _load_healing_context(run_id)
    goal = build_self_heal_goal(case, healing_context) if healing_context else build_agent_goal(case)
    plan = plan_agent_execution(case)
    trace: dict[str, Any] = {
        "ok": False,
        "status": "running",
        "goal": goal,
        "history": [],
        "run_id": run_id,
        "case_id": case_id,
        "case_arg": case_arg,
        "trigger": "self_heal" if healing_context else "manual",
        "parent_run_id": str(healing_context.get("parent_run_id") or "") if healing_context else "",
        "healing_hint": str(healing_context.get("healing_hint") or "") if healing_context else "",
        "allowed_hosts": sorted(allowed_hosts),
        "plan": plan,
        "stage_runs": [],
        "current_stage_id": "",
        "current_stage_name": "",
        "current_strategy": "",
    }
    _write_trace_snapshot(run_id, trace)

    try:
        for stage in plan.get("stages") or []:
            started_at = now_iso()
            stage_run = stage_view(stage, status="running", started_at=started_at)
            trace["stage_runs"].append(stage_run)
            _finalize_stage_runs(
                trace,
                current_stage_id=str(stage.get("stage_id") or ""),
                current_stage_name=str(stage.get("name") or ""),
                current_strategy=str(stage.get("strategy") or ""),
            )
            _write_trace_snapshot(run_id, trace)

            stage_ok, stage_history, stage_error = await execute_stage_strategy(page, system, case, stage)
            if stage_history:
                trace["history"].extend(normalize_stage_history(stage_history, len(trace["history"]), stage))
            if stage_ok:
                stage_run.update(stage_view(stage, status="completed", started_at=started_at, finished_at=now_iso()))
                _write_trace_snapshot(run_id, trace)
                continue

            if stage.get("fallback") == "generic_explore":
                stage_goal = build_stage_goal(case, plan, stage)
                fallback_result = await run_generic_stage_loop(page, stage_goal, allowed_hosts, max_steps=12)
                trace["history"].extend(normalize_stage_history(fallback_result.get("history") or [], len(trace["history"]), stage))
                if fallback_result.get("ok"):
                    stage_run.update(stage_view(stage, status="completed", fallback_used=True, started_at=started_at, finished_at=now_iso()))
                    _write_trace_snapshot(run_id, trace)
                    continue
                stage_error = str(fallback_result.get("error") or stage_error or "generic stage fallback failed")
                stage_run.update(stage_view(stage, status="failed", fallback_used=True, error=stage_error, started_at=started_at, finished_at=now_iso()))
                trace.update(
                    {
                        "ok": False,
                        "status": "failed",
                        "error": stage_error,
                        "summary": f"阶段失败：{stage.get('name')}",
                        "final_url": page.url,
                    }
                )
                _write_trace_snapshot(run_id, trace)
                break

            stage_run.update(stage_view(stage, status="failed", error=stage_error, started_at=started_at, finished_at=now_iso()))
            trace.update(
                {
                    "ok": False,
                    "status": "failed",
                    "error": stage_error,
                    "summary": f"阶段失败：{stage.get('name')}",
                    "final_url": page.url,
                }
            )
            _write_trace_snapshot(run_id, trace)
            break
        else:
            trace.update(
                {
                    "ok": True,
                    "status": "passed",
                    "summary": f"已完成 {len(plan.get('stages') or [])} 个阶段",
                    "final_url": page.url,
                }
            )
        await screenshot(page, run_id, case_id, "03-final.png")
    except Exception as exc:
        trace.update({"ok": False, "status": "failed", "error": str(exc), "final_url": page.url if getattr(page, "url", "") else ""})
    finally:
        await evidence.dom_snapshot(page, "agent-final.html")
        await evidence.stop(page)

    _finalize_stage_runs(trace)
    trace["evidence"] = evidence_summary(run_id)
    artifact_paths = _write_trace_artifacts(run_id, trace, case)
    return {
        **trace,
        **artifact_paths,
        "status": "passed" if trace.get("ok") else "failed",
    }
