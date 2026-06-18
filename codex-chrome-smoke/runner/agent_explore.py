from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

from runner.agent_codegen import generate_candidate_flow
from runner.browser import load_case, load_case_file, load_system, open_login_page, screenshot
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
    lines.extend(f"- {item}" for item in case.get("expected_results") or [])

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
    base_goal = build_agent_goal(case)
    lines = [base_goal, "", "Self-heal context:"]
    failure_summary = str(healing_context.get("failure_summary") or "").strip()
    healing_hint = str(healing_context.get("healing_hint") or "").strip()
    if failure_summary:
        lines.append(f"- Previous failure: {failure_summary}")
    if healing_hint:
        lines.append(f"- Healing hint: {healing_hint}")
    lines.append("- Do not repeat the previous invalid or noisy tail action.")
    lines.append("- If success signals are already visible, finish immediately instead of adding extra actions.")
    last_steps = healing_context.get("last_history") or []
    if last_steps:
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
    return await page.evaluate(
        """() => {
          const visible = (el) => {
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
          };
          const esc = (value) => window.CSS && CSS.escape
            ? CSS.escape(value)
            : String(value).replace(/["\\\\#.;?+*~':!^$[\\]()=>|/@]/g, "\\\\$&");
          const selectorFor = (el) => {
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
          const textOf = (el) =>
            (el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('placeholder') || '')
              .replace(/\\s+/g, ' ')
              .trim()
              .slice(0, 120);
          const interactives = Array.from(
            document.querySelectorAll('a,button,input,textarea,select,[role="button"],[role="link"],[contenteditable="true"]')
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
    )


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
        raw_decision = await decide(goal, observation, history, step_index, max_steps)
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
            history.append({"step": step_index + 1, "decision": decision_dict, "observation": observation})
            return {"ok": True, "status": "passed", "goal": goal, "history": history, "summary": decision.reason}
        if decision.action == "fail":
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
        "6. If the goal is complete, return {\"action\":\"finish\",\"reason\":\"...\"}.\n"
        "7. If blocked, return {\"action\":\"fail\",\"reason\":\"...\"}.\n\n"
        "Examples:\n"
        "{\"action\":\"fill\",\"ref\":\"e1\",\"value\":\"test\",\"reason\":\"fill username from case test data\"}\n"
        "{\"action\":\"fill\",\"ref\":\"e2\",\"value\":\"123456\",\"reason\":\"fill password from case test data\"}\n"
        "{\"action\":\"click\",\"ref\":\"e2\",\"reason\":\"submit form\"}\n"
        "{\"action\":\"assert_text\",\"value\":\"Home\",\"reason\":\"verify homepage\"}\n\n"
        f"Recent history:\n{json.dumps(compact_history, ensure_ascii=False, indent=2)}\n\n"
        f"Current observation:\n{json.dumps(observation, ensure_ascii=False, indent=2)}"
    )


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise ValueError(f"AI response did not contain JSON: {text[:300]}")
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("AI response JSON must be an object")
    return parsed


def _chat_content(payload: dict[str, Any]) -> str:
    choice = (payload.get("choices") or [{}])[0]
    content = ((choice.get("message") or {}).get("content") or choice.get("text") or payload.get("reply") or "").strip()
    if content:
        return content
    raise ValueError(f"AI response has no message content: {json.dumps(payload, ensure_ascii=False)[:500]}")


async def decide_next_action(goal: str, observation: dict[str, Any], history: list[dict[str, Any]], step_index: int, max_steps: int) -> dict[str, Any]:
    from icm_platform.ai_service import AIConfigurationError, AIService
    from icm_platform.db import get_ai_settings

    settings = get_ai_settings(mask_key=False)
    if not settings.get("api_key") or not settings.get("base_url") or not settings.get("model"):
        raise AIConfigurationError("Agent Explore requires configured AI provider, base_url, model, and api_key.")

    service = AIService()
    provider = settings.get("provider", service.provider)
    prompt = build_agent_prompt(goal, observation, history, step_index, max_steps)
    payload = {
        "model": settings["model"],
        "messages": [
            {
                "role": "system",
                "content": "You are a bounded browser automation Agent. Return exactly one valid JSON object.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 1200,
    }
    raw = service._post_json(
        service.chat_completions_url(settings["base_url"]),
        service.api_key_for_provider(settings),
        payload,
        timeout=service.request_timeout(provider),
    )
    return extract_json_object(_chat_content(raw))


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
    selector = target["selector"]
    locator = page.locator(selector).first
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


def _write_trace_artifacts(run_id: str, trace: dict[str, Any]) -> dict[str, str]:
    out_dir = AGENT_REPORT_ROOT / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    trace_path = out_dir / "trace.json"
    trace_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
    paths = {"trace_path": str(trace_path.relative_to(ROOT))}
    if trace.get("ok"):
        candidate_path = out_dir / "candidate_flow.py"
        candidate_path.write_text(generate_candidate_flow(trace), encoding="utf-8")
        paths["candidate_flow_path"] = str(candidate_path.relative_to(ROOT))
    return paths


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
    await open_login_page(page, system)
    await screenshot(page, run_id, case_id, "01-entry.png")
    healing_context = _load_healing_context(run_id)
    goal = build_self_heal_goal(case, healing_context) if healing_context else build_agent_goal(case)

    async def observe() -> dict[str, Any]:
        return await observe_page(page)

    async def decide(goal_text: str, observation: dict[str, Any], history: list[dict[str, Any]], step_index: int, max_steps: int) -> dict[str, Any]:
        return await decide_next_action(goal_text, observation, history, step_index, max_steps)

    async def execute(decision, observation: dict[str, Any]) -> dict[str, Any]:
        try:
            result = await execute_agent_decision(page, decision, observation)
            evidence.event(page, "agent_action", f"executed {decision.action}", selectors=[result.get("selector", "")], value=decision.value)
            return result
        except Exception as exc:
            evidence.event(page, "agent_action_failed", f"failed {decision.action}", error=str(exc))
            return {"result": "error", "action": decision.action, "ref": decision.ref, "error": str(exc)}

    try:
        result = await run_agent_loop(
            goal=goal,
            observe=observe,
            decide=decide,
            execute=execute,
            allowed_hosts=allowed_hosts,
            max_steps=25,
        )
        await screenshot(page, run_id, case_id, "03-final.png")
    except Exception as exc:
        result = {"ok": False, "status": "failed", "goal": goal, "history": [], "error": str(exc)}
    finally:
        await evidence.dom_snapshot(page, "agent-final.html")
        await evidence.stop(page)

    trace = {
        **result,
        "run_id": run_id,
        "case_id": case_id,
        "case_arg": case_arg,
        "trigger": "self_heal" if healing_context else "manual",
        "parent_run_id": str(healing_context.get("parent_run_id") or "") if healing_context else "",
        "healing_hint": str(healing_context.get("healing_hint") or "") if healing_context else "",
        "allowed_hosts": sorted(allowed_hosts),
        "evidence": evidence_summary(run_id),
    }
    artifact_paths = _write_trace_artifacts(run_id, trace)
    return {
        **trace,
        **artifact_paths,
        "status": "passed" if result.get("ok") else "failed",
    }
