from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

from runner.agent_codegen import generate_candidate_flow
from runner.case_expectations import case_expected_results
from runner.agent_stage_router import build_stage_goal, execute_stage_strategy, normalize_stage_history, now_iso, plan_agent_execution, stage_view
from runner.browser import attach_case_runtime, ensure_logged_out, first_visible, load_case, load_case_file, load_system, open_login_page, screenshot
from runner.element_ref_matcher import build_agent_ref_evidence, format_agent_ref_guidance, resolve_recovery_ref
from runner.element_feedback import feedback_enabled, record_element_feedback
from runner.element_retry_strategy import retry_once_with_healing
from runner.evidence_recorder import attach_evidence_recorder, evidence_summary
from runner.operation_knowledge import load_trusted_plan, write_pending_agent_asset
from icm_platform.paths import DB_PATH, TEST_CASE_DIR


ROOT = Path(__file__).resolve().parents[1]
AGENT_REPORT_ROOT = ROOT / "reports" / "agent-explore"
AGENT_KNOWLEDGE_ROOT = ROOT / "reports" / "agent-knowledge"


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
            const popupMenu = el.closest('ul[id]');
            if (popupMenu && popupMenu.id) {
              const siblings = Array.from(popupMenu.children).filter((child) => child.tagName === el.tagName);
              const index = siblings.indexOf(el) + 1;
              if (index > 0) return `#${esc(popupMenu.id)} > ${el.tagName.toLowerCase()}:nth-of-type(${index})`;
            }
            if (el.id) return `#${esc(el.id)}`;
            const testId = el.getAttribute('data-testid') || el.getAttribute('data-test');
            if (testId) return `[data-testid="${esc(testId)}"],[data-test="${esc(testId)}"]`;
            const name = el.getAttribute('name');
            if (name) return `${el.tagName.toLowerCase()}[name="${esc(name)}"]`;
            const placeholder = el.getAttribute('placeholder');
            if (placeholder) return `${el.tagName.toLowerCase()}[placeholder="${esc(placeholder)}"]`;
            if (el.matches && el.matches('img.el-tooltip.button') && el.parentElement && el.parentElement.classList.contains('top_button')) {
              const icons = Array.from(el.parentElement.children).filter((child) => child.tagName === 'IMG');
              const iconIndex = icons.indexOf(el) + 1;
              if (iconIndex > 0) return `.top_button > img.el-tooltip.button:nth-of-type(${iconIndex})`;
            }

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
            const tooltipId = el.getAttribute('aria-describedby');
            const tooltip = tooltipId ? document.getElementById(tooltipId) : null;
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
              tooltip && (tooltip.innerText || tooltip.textContent),
              descendants.join(' '),
              closestMenu && (closestMenu.innerText || closestMenu.textContent || closestMenu.getAttribute('title')),
              hrefLabel,
            ])
              .join(' | ')
              .slice(0, 160);
          };
          const routeOf = (el) => {
            const anchor = el.closest && el.closest('a[href]');
            return (anchor && anchor.getAttribute('href'))
              || el.getAttribute('href')
              || el.getAttribute('data-index')
              || el.getAttribute('index')
              || el.getAttribute('data-route')
              || el.getAttribute('to')
              || '';
          };
          const interactives = Array.from(
            document.querySelectorAll(
              'a,button,input,textarea,select,[role="button"],[role="link"],[role="menuitem"],[contenteditable="true"],img[tabindex]:not([tabindex="-1"]),.screen-top-head[tabindex],.el-slider__button-wrapper[tabindex],.el-submenu__title,.el-menu-item,.el-dropdown-menu__item'
            )
          )
            .filter(visible)
            .slice(0, 180)
            .map((el, index) => ({
              ref: `e${index + 1}`,
              tag: el.tagName.toLowerCase(),
              role: el.getAttribute('role') || '',
              type: el.getAttribute('type') || '',
              text: el.getAttribute('type') === 'password' ? (el.getAttribute('placeholder') || '') : textOf(el),
              valueLength: el.getAttribute('type') === 'password' ? String(el.value || '').length : undefined,
              ariaLabel: el.getAttribute('aria-label') || '',
              placeholder: el.getAttribute('placeholder') || '',
              name: el.getAttribute('name') || '',
              testId: el.getAttribute('data-testid') || el.getAttribute('data-test') || '',
              testIdAttribute: el.hasAttribute('data-testid') ? 'data-testid' : (el.hasAttribute('data-test') ? 'data-test' : ''),
              selector: selectorFor(el),
              href: routeOf(el),
              disabled: Boolean(el.disabled || el.getAttribute('aria-disabled') === 'true'),
            }));
          const visibleText = (document.body && document.body.innerText || '')
            .split(/\\n+/)
            .map((line) => line.replace(/\\s+/g, ' ').trim())
            .filter(Boolean)
            .slice(0, 35);
          const navigationLinks = Array.from(document.querySelectorAll('a[href],[data-index],[index],[data-route],[to],.el-menu-item,.el-submenu__title'))
            .filter(visible)
            .map((node) => ({
              href: routeOf(node),
              text: textOf(node),
              ariaLabel: node.getAttribute('aria-label') || '',
              selector: selectorFor(node),
            }))
            .filter((item) => item.href)
            .slice(0, 120);
          const dialogs = Array.from(document.querySelectorAll('[role="dialog"],.el-dialog,.el-message-box'))
            .filter(visible)
            .map((node) => ({ text: normalizeText(node.innerText || node.textContent || ''), selector: selectorFor(node) }))
            .slice(0, 6);
          return { url: location.href, title: document.title, visibleText, interactives, navigationLinks, dialogs };
        }"""


def _is_network_provider_error(exc: Exception) -> bool:
    """判断异常是否为 AI provider 网络错误（值得重试），而非 JSON 解析或配置错误。"""
    return type(exc).__name__ == "AIProviderError"


def _is_pre_action_locator_error(error: str) -> bool:
    return error.startswith("unknown ref:") or error.startswith("Agent target is not visible:")


def _pre_action_locator_category(error: str) -> str:
    return "unknown_ref" if error.startswith("unknown ref:") else "target_not_visible"


async def _execute_once(execute, decision, observation: dict[str, Any]) -> dict[str, Any]:
    try:
        maybe_execution = execute(decision, observation)
        execution = await maybe_execution if hasattr(maybe_execution, "__await__") else maybe_execution
    except Exception as exc:
        return {"result": "error", "action": decision.action, "ref": decision.ref, "error": str(exc)}
    return execution if isinstance(execution, dict) else {"result": "ok"}


async def _recover_pre_action_locator(
    *,
    goal: str,
    decision,
    error: str,
    observe,
    execute,
    allowed_hosts: set[str],
) -> tuple[dict[str, Any] | None, dict[str, Any], Any | None]:
    if decision.action not in {"click", "fill", "hover"} or not _is_pre_action_locator_error(error):
        return None, {"status": "not_eligible"}, None

    from runner.agent_actions import validate_decision

    refreshed_observation = await observe()
    recovery = resolve_recovery_ref(
        f"{goal}\n{decision.reason}",
        str(refreshed_observation.get("url") or ""),
        refreshed_observation,
        decision.action,
    )
    recovery["failure_category"] = _pre_action_locator_category(error)
    if recovery.get("status") != "resolved":
        return None, recovery, None
    recovered_decision = replace(decision, ref=str(recovery["ref"]))
    observed_refs = {item.get("ref", "") for item in refreshed_observation.get("interactives") or []}
    errors = validate_decision(recovered_decision, observed_refs=observed_refs, allowed_hosts=allowed_hosts)
    if errors:
        return None, {"status": "invalid_rebound_ref", "error": "; ".join(errors)}, None
    execution = await _execute_once(execute, recovered_decision, refreshed_observation)
    recovery["observation"] = refreshed_observation
    return execution, recovery, recovered_decision


async def run_agent_loop(
    goal: str,
    observe: Callable[[], Awaitable[dict[str, Any]]],
    decide: Callable[[str, dict[str, Any], list[dict[str, Any]], int, int], Awaitable[dict[str, Any]]],
    execute: Callable[[Any, dict[str, Any]], Awaitable[dict[str, Any]] | dict[str, Any] | None],
    allowed_hosts: set[str],
    max_steps: int = 25,
    on_history: Callable[[list[dict[str, Any]]], None] | None = None,
) -> dict[str, Any]:
    from runner.agent_actions import normalize_decision, validate_decision

    history: list[dict[str, Any]] = []

    def record_history(item: dict[str, Any]) -> None:
        observation = item.get("observation") or {}
        decision = item.get("decision") or {}
        visible_text = observation.get("visibleText") or []
        if isinstance(visible_text, list):
            visible_text = " ".join(str(value) for value in visible_text[:20])
        route = str(observation.get("url") or "")
        intent = "\n".join(
            value
            for value in (
                goal,
                str(decision.get("reason") or ""),
                route,
                str(observation.get("title") or ""),
                str(visible_text or ""),
            )
            if value
        )
        item["element_knowledge"] = {
            **build_agent_ref_evidence(
            intent,
            route,
            observation,
            str(decision.get("ref") or ""),
            ),
            "decision_source": "agent_decision",
            "observation_phase": "pre_action",
        }
        history.append(item)
        if on_history:
            on_history(history)

    for step_index in range(max_steps):
        observation = await observe()
        try:
            raw_decision = await decide(goal, observation, history, step_index, max_steps)
        except Exception as exc:
            if step_index == 0 or not _is_network_provider_error(exc):
                record_history(
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
            await asyncio.sleep(2)
            try:
                raw_decision = await decide(goal, observation, history, step_index, max_steps)
            except Exception as retry_exc:
                record_history(
                    {
                        "step": step_index + 1,
                        "decision": {
                            "action": "fail",
                            "ref": "",
                            "url": "",
                            "value": "",
                            "key": "",
                            "reason": str(retry_exc),
                        },
                        "observation": observation,
                        "execution": {"result": "error", "error": str(retry_exc)},
                    }
                )
                return {"ok": False, "status": "failed", "goal": goal, "history": history, "error": str(retry_exc)}
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
                record_history(
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
            record_history({"step": step_index + 1, "decision": decision_dict, "observation": observation})
            return {"ok": True, "status": "passed", "goal": goal, "history": history, "summary": decision.reason}
        if decision.action == "fail":
            if _should_continue_after_login_satisfied(goal, observation, history, decision.reason):
                record_history(
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
            record_history({"step": step_index + 1, "decision": decision_dict, "observation": observation})
            return {"ok": False, "status": "failed", "goal": goal, "history": history, "error": decision.reason}

        observed_refs = {item.get("ref", "") for item in observation.get("interactives") or []}
        errors = validate_decision(decision, observed_refs=observed_refs, allowed_hosts=allowed_hosts)
        if errors and _should_finish_on_success_signal(goal, observation, history, decision, errors):
            record_history(
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
            error = "; ".join(errors)
            recovered_execution, recovery, recovered_decision = await _recover_pre_action_locator(
                goal=goal,
                decision=decision,
                error=error,
                observe=observe,
                execute=execute,
                allowed_hosts=allowed_hosts,
            )
            if recovered_decision is not None and recovered_execution and recovered_execution.get("result") != "error":
                refreshed_observation = recovery.pop("observation", observation)
                record_history(
                    {
                        "step": step_index + 1,
                        "decision": {
                            "action": recovered_decision.action,
                            "ref": recovered_decision.ref,
                            "url": recovered_decision.url,
                            "value": recovered_decision.value,
                            "key": recovered_decision.key,
                            "reason": recovered_decision.reason,
                        },
                        "observation": refreshed_observation,
                        "execution": {**recovered_execution, "recovery": {"original_ref": decision.ref, "error": error, **recovery}},
                    }
                )
                continue
            record_history(
                {
                    "step": step_index + 1,
                    "decision": decision_dict,
                    "observation": observation,
                    "execution": {"result": "error", "error": error, "recovery": recovery},
                }
            )
            return {"ok": False, "status": "failed", "goal": goal, "history": history, "error": error}

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
            record_history(
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

        execution = await _execute_once(execute, decision, observation)
        if execution.get("result") == "error":
            error = str(execution.get("error") or "agent action failed")
            recovered_execution, recovery, recovered_decision = await _recover_pre_action_locator(
                goal=goal,
                decision=decision,
                error=error,
                observe=observe,
                execute=execute,
                allowed_hosts=allowed_hosts,
            )
            if recovered_decision is not None and recovered_execution and recovered_execution.get("result") != "error":
                refreshed_observation = recovery.pop("observation", observation)
                record_history(
                    {
                        "step": step_index + 1,
                        "decision": {
                            "action": recovered_decision.action,
                            "ref": recovered_decision.ref,
                            "url": recovered_decision.url,
                            "value": recovered_decision.value,
                            "key": recovered_decision.key,
                            "reason": recovered_decision.reason,
                        },
                        "observation": refreshed_observation,
                        "execution": {**recovered_execution, "recovery": {"original_ref": decision.ref, "error": error, **recovery}},
                    }
                )
                continue
            record_history(
                {
                    "step": step_index + 1,
                    "decision": decision_dict,
                    "observation": observation,
                    "execution": {**execution, "recovery": recovery},
                }
            )
            return {
                "ok": False,
                "status": "failed",
                "goal": goal,
                "history": history,
                "error": error,
            }
        record_history(
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
    return "login" in goal_text or "登录" in goal


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
    if str(getattr(decision, "action", "")) not in {"click", "fill", "hover", "press"}:
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
    visible_text = observation.get("visibleText") or []
    if isinstance(visible_text, list):
        visible_excerpt = " ".join(str(item) for item in visible_text[:20])
    else:
        visible_excerpt = str(visible_text)
    route = str(observation.get("url") or "")
    intent = "\n".join(
        item
        for item in [
            goal,
            route,
            str(observation.get("title") or ""),
            visible_excerpt,
        ]
        if item
    )
    candidate_elements = format_agent_ref_guidance(intent, route, observation, top_k=6)
    shared_element_knowledge = ""
    if candidate_elements:
        shared_element_knowledge = (
            "\n\nShared element knowledge (advisory only):\n"
            f"{candidate_elements}\n"
            "Important: shared element knowledge is advisory only. "
            "To execute click/fill/hover/press, choose a current ref from observation.interactives. "
            "Do not invent selectors from the shared library."
        )
    return (
        "You are a bounded browser automation Agent for ICM regression exploration.\n"
        "Return exactly one JSON object. Do not return Markdown or explanations.\n\n"
        f"Goal:\n{goal}\n\n"
        f"Step: {step_index + 1}/{max_steps}\n\n"
        "Allowed actions: goto, fill, click, hover, press, wait, scroll, assert_text, finish, fail.\n"
        "Safety rules:\n"
        "1. click/fill/hover/press must use a ref from observation.interactives.\n"
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
        "{\"action\":\"hover\",\"ref\":\"e3\",\"reason\":\"reveal hover menu\"}\n"
        "{\"action\":\"assert_text\",\"value\":\"Home\",\"reason\":\"verify homepage\"}\n\n"
        f"Recent history:\n{json.dumps(compact_history, ensure_ascii=False, indent=2)}\n\n"
        f"{shared_element_knowledge}\n\n"
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
    if action in {"click", "hover"}:
        candidates.extend(f"text={text}" for text in _target_text_candidates(target))
    deduped: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in deduped:
            deduped.append(candidate)
    return deduped


def _is_pointer_intercept_error(exc: Exception) -> bool:
    return "intercepts pointer events" in str(exc)


def _target_looks_like_dropdown_trigger(target: dict[str, Any]) -> bool:
    text = " ".join(
        str(target.get(key) or "").strip().lower()
        for key in ("text", "ariaLabel", "selector")
    )
    return any(token in text for token in ("更多", "more", "dropdown", "aria-haspopup", "el-dropdown-selfdefine"))


async def _visible_dropdown_menu_item_count(page) -> int:
    locator = page.locator(".el-dropdown-menu__item")
    return await locator.locator(":visible").count()


async def _dismiss_stale_hover_overlay(page) -> None:
    await page.keyboard.press("Escape")
    await page.mouse.move(1, 1)
    await page.wait_for_timeout(120)


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
    network_retries = 2
    for attempt in range(2):
        payload = _agent_decision_payload(settings["model"], provider, prompt, parse_error)
        for network_attempt in range(network_retries + 1):
            try:
                raw = service._post_json(
                    service.chat_completions_url(settings["base_url"]),
                    service.api_key_for_provider(settings),
                    payload,
                    timeout=service.request_timeout(provider),
                )
                break
            except Exception as network_exc:
                if network_attempt == network_retries:
                    raise
                await asyncio.sleep(2)
        try:
            return extract_json_object(_chat_content(raw))
        except ValueError as exc:
            parse_error = str(exc)
            if attempt == 1:
                raise ValueError(f"AI 决策返回的 JSON 不完整或格式错误，请重新执行本用例。原始错误：{parse_error}") from exc
    raise ValueError(f"AI 决策返回的 JSON 不完整或格式错误，请重新执行本用例。原始错误：{parse_error}")


def _feedback_page_id(observation: dict[str, Any]) -> str:
    route = str(observation.get("url") or "")
    parsed = urlparse(route)
    fragment = parsed.fragment or parsed.path or route
    value = re.sub(r"[^0-9a-zA-Z]+", "_", fragment).strip("_").lower()
    return value or "unknown_page"


def _record_agent_action_feedback(
    *,
    decision,
    observation: dict[str, Any],
    target: dict[str, Any] | None,
    selector: str,
    success: bool,
    duration_ms: int,
    error: str | None = None,
) -> None:
    if str(getattr(decision, "action", "")) not in {"click", "fill", "hover", "press"}:
        return
    if not feedback_enabled():
        return
    try:
        record_element_feedback(
            element_id=str((target or {}).get("element_id") or (target or {}).get("matched_element_id") or ""),
            page_id=str((target or {}).get("page_id") or observation.get("page_id") or _feedback_page_id(observation)),
            state=str((target or {}).get("state") or observation.get("state") or "default"),
            action=str(getattr(decision, "action", "")),
            selector=selector or str((target or {}).get("selector") or ""),
            success=success,
            duration_ms=duration_ms,
            url=str(observation.get("url") or ""),
            error=error,
        )
    except Exception:
        # Feedback must never break the bounded Agent execution path.
        return


async def execute_agent_decision(page, decision, observation: dict[str, Any]) -> dict[str, Any]:
    started_at = time.perf_counter()
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
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        _record_agent_action_feedback(
            decision=decision,
            observation=observation,
            target=None,
            selector="",
            success=True,
            duration_ms=duration_ms,
        )
        return {"result": "pressed", "ref": "", "key": decision.key or "Enter", "selector": ""}
    if not target:
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        error = f"Agent selected unknown ref: {decision.ref}"
        _record_agent_action_feedback(
            decision=decision,
            observation=observation,
            target=None,
            selector="",
            success=False,
            duration_ms=duration_ms,
            error=error,
        )
        raise RuntimeError(error)
    selector_candidates = _target_selector_candidates(target, decision.action)
    locator = await first_visible(page, selector_candidates)
    if locator is None:
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        error = f"Agent target is not visible: {selector_candidates}"
        _record_agent_action_feedback(
            decision=decision,
            observation=observation,
            target=target,
            selector=selector_candidates[0] if selector_candidates else "",
            success=False,
            duration_ms=duration_ms,
            error=error,
        )
        raise RuntimeError(error)
    selector = selector_candidates[0] if selector_candidates else ""
    if decision.action == "fill":
        retried_steps: list[str] = []

        async def fill_operation():
            await locator.fill(decision.value, timeout=8000)

        try:
            await fill_operation()
        except Exception as exc:
            try:
                retried, retried_steps = await retry_once_with_healing(
                    page=page,
                    action=decision.action,
                    target=target,
                    locator=locator,
                    error=exc,
                    operation=fill_operation,
                )
            except Exception as retry_exc:
                duration_ms = int((time.perf_counter() - started_at) * 1000)
                _record_agent_action_feedback(
                    decision=decision,
                    observation=observation,
                    target=target,
                    selector=selector,
                    success=False,
                    duration_ms=duration_ms,
                    error=str(retry_exc),
                )
                raise
            if not retried:
                duration_ms = int((time.perf_counter() - started_at) * 1000)
                _record_agent_action_feedback(
                    decision=decision,
                    observation=observation,
                    target=target,
                    selector=selector,
                    success=False,
                    duration_ms=duration_ms,
                    error=str(exc),
                )
                raise
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        _record_agent_action_feedback(
            decision=decision,
            observation=observation,
            target=target,
            selector=selector,
            success=True,
            duration_ms=duration_ms,
        )
        result = {"result": "filled", "ref": decision.ref, "selector": selector}
        if retried_steps:
            result["healing_retry"] = retried_steps
        return result
    if decision.action == "click":
        retried_steps: list[str] = []

        async def click_operation():
            await locator.click(timeout=8000)

        try:
            await click_operation()
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            _record_agent_action_feedback(
                decision=decision,
                observation=observation,
                target=target,
                selector=selector,
                success=True,
                duration_ms=duration_ms,
            )
            result = {"result": "clicked", "ref": decision.ref, "selector": selector}
            if retried_steps:
                result["healing_retry"] = retried_steps
            return result
        except Exception as exc:
            if not _is_pointer_intercept_error(exc):
                try:
                    retried, retried_steps = await retry_once_with_healing(
                        page=page,
                        action=decision.action,
                        target=target,
                        locator=locator,
                        error=exc,
                        operation=click_operation,
                    )
                except Exception as retry_exc:
                    duration_ms = int((time.perf_counter() - started_at) * 1000)
                    _record_agent_action_feedback(
                        decision=decision,
                        observation=observation,
                        target=target,
                        selector=selector,
                        success=False,
                        duration_ms=duration_ms,
                        error=str(retry_exc),
                    )
                    raise
                if retried:
                    duration_ms = int((time.perf_counter() - started_at) * 1000)
                    _record_agent_action_feedback(
                        decision=decision,
                        observation=observation,
                        target=target,
                        selector=selector,
                        success=True,
                        duration_ms=duration_ms,
                    )
                    return {"result": "clicked", "ref": decision.ref, "selector": selector, "healing_retry": retried_steps}
                duration_ms = int((time.perf_counter() - started_at) * 1000)
                _record_agent_action_feedback(
                    decision=decision,
                    observation=observation,
                    target=target,
                    selector=selector,
                    success=False,
                    duration_ms=duration_ms,
                    error=str(exc),
                )
                raise
            if not _target_looks_like_dropdown_trigger(target):
                duration_ms = int((time.perf_counter() - started_at) * 1000)
                _record_agent_action_feedback(
                    decision=decision,
                    observation=observation,
                    target=target,
                    selector=selector,
                    success=False,
                    duration_ms=duration_ms,
                    error=str(exc),
                )
                raise
            if await _visible_dropdown_menu_item_count(page) <= 0:
                duration_ms = int((time.perf_counter() - started_at) * 1000)
                _record_agent_action_feedback(
                    decision=decision,
                    observation=observation,
                    target=target,
                    selector=selector,
                    success=False,
                    duration_ms=duration_ms,
                    error=str(exc),
                )
                raise
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            _record_agent_action_feedback(
                decision=decision,
                observation=observation,
                target=target,
                selector=selector,
                success=True,
                duration_ms=duration_ms,
            )
            return {"result": "dropdown_opened", "ref": decision.ref, "selector": selector}
    if decision.action == "hover":
        try:
            await locator.hover(timeout=8000)
        except Exception as exc:
            if not _is_pointer_intercept_error(exc):
                duration_ms = int((time.perf_counter() - started_at) * 1000)
                _record_agent_action_feedback(
                    decision=decision,
                    observation=observation,
                    target=target,
                    selector=selector,
                    success=False,
                    duration_ms=duration_ms,
                    error=str(exc),
                )
                raise
            try:
                await _dismiss_stale_hover_overlay(page)
                await locator.hover(timeout=8000)
            except Exception as retry_exc:
                duration_ms = int((time.perf_counter() - started_at) * 1000)
                _record_agent_action_feedback(
                    decision=decision,
                    observation=observation,
                    target=target,
                    selector=selector,
                    success=False,
                    duration_ms=duration_ms,
                    error=str(retry_exc),
                )
                raise
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        _record_agent_action_feedback(
            decision=decision,
            observation=observation,
            target=target,
            selector=selector,
            success=True,
            duration_ms=duration_ms,
        )
        return {"result": "hovered", "ref": decision.ref, "selector": selector}
    if decision.action == "press":
        try:
            await locator.press(decision.key or "Enter", timeout=8000)
        except Exception as exc:
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            _record_agent_action_feedback(
                decision=decision,
                observation=observation,
                target=target,
                selector=selector,
                success=False,
                duration_ms=duration_ms,
                error=str(exc),
            )
            raise
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        _record_agent_action_feedback(
            decision=decision,
            observation=observation,
            target=target,
            selector=selector,
            success=True,
            duration_ms=duration_ms,
        )
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
    pending_path = trace_path.with_suffix(".json.tmp")
    pending_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
    pending_path.replace(trace_path)


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
    system = load_system(case["system"], case)
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
    plan = load_trusted_plan(
        case,
        plan_agent_execution(case),
        db_path=DB_PATH,
        case_dir=TEST_CASE_DIR,
        flow_dir=ROOT / "runner" / "flows",
    )
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
    if trace.get("ok"):
        pending_path = write_pending_agent_asset(AGENT_KNOWLEDGE_ROOT, run_id, case, trace)
        trace["pending_review_path"] = str(pending_path.relative_to(ROOT))
    artifact_paths = _write_trace_artifacts(run_id, trace, case)
    return {
        **trace,
        **artifact_paths,
        "status": "passed" if trace.get("ok") else "failed",
    }
