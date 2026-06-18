# ICM Agent Explore Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a bounded sidecar Agent exploration mode that can run ICM YAML cases, capture successful exploration traces, and generate review-only candidate regression flow code.

**Architecture:** Add `agent-explore` beside the existing runner path without changing deterministic `run-case`, `run-batch`, or `run-draft`. Implement the Agent loop in Python so it uses the current Playwright session, evidence recorder, runtime settings, and worker queue. Generate candidate code only after successful exploration and keep manual registration separate.

**Tech Stack:** Python 3.10+, FastAPI, Playwright async API, PyYAML, existing `runner` and `icm_platform` modules.

---

## File Structure

- Create `codex-chrome-smoke/runner/agent_actions.py`: normalize, validate, whitelist, and execute Agent actions.
- Create `codex-chrome-smoke/runner/agent_explore.py`: build goals, observe pages, call AI, loop through Agent decisions, and write trace artifacts.
- Create `codex-chrome-smoke/runner/agent_codegen.py`: convert a successful trace into a review-only candidate Python flow.
- Modify `codex-chrome-smoke/runner/main.py`: add `agent-explore` command and dispatch.
- Modify `codex-chrome-smoke/icm_platform/worker.py`: allow queueing and running `agent-explore`.
- Modify `codex-chrome-smoke/icm_platform/api.py`: extend run request mode to include `agent-explore`.
- Add tests under `codex-chrome-smoke/runner/tests/` and `codex-chrome-smoke/icm_platform/tests/`.

### Task 1: Agent Action Safety Layer

**Files:**
- Create: `codex-chrome-smoke/runner/agent_actions.py`
- Test: `codex-chrome-smoke/runner/tests/test_agent_actions.py`

- [ ] **Step 1: Write failing tests**

```python
from runner.agent_actions import AgentDecision, normalize_decision, validate_decision


def test_normalize_rejects_unknown_action():
    decision = normalize_decision({"action": "delete", "reason": "bad"})
    assert decision.action == "fail"
    assert "unsupported" in decision.reason


def test_click_requires_observed_ref():
    decision = AgentDecision(action="click", ref="e99", reason="click missing")
    errors = validate_decision(decision, observed_refs={"e1", "e2"}, allowed_hosts={"127.0.0.1"})
    assert "unknown ref" in errors[0]


def test_goto_rejects_host_outside_whitelist():
    decision = AgentDecision(action="goto", url="https://example.com", reason="external")
    errors = validate_decision(decision, observed_refs=set(), allowed_hosts={"127.0.0.1"})
    assert "host not allowed" in errors[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest codex-chrome-smoke/runner/tests/test_agent_actions.py -v`

Expected: FAIL because `runner.agent_actions` does not exist.

- [ ] **Step 3: Implement minimal action model**

```python
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


SAFE_ACTIONS = {"goto", "fill", "click", "press", "wait", "scroll", "assert_text", "finish", "fail"}
REF_ACTIONS = {"fill", "click", "press"}


@dataclass(slots=True)
class AgentDecision:
    action: str
    ref: str = ""
    url: str = ""
    value: str = ""
    key: str = ""
    reason: str = ""


def _text(value: object) -> str:
    return str(value or "").strip()


def normalize_decision(raw: dict) -> AgentDecision:
    action = _text(raw.get("action"))
    if action not in SAFE_ACTIONS:
        return AgentDecision(action="fail", reason=f"unsupported action: {action or 'empty'}")
    return AgentDecision(
        action=action,
        ref=_text(raw.get("ref")),
        url=_text(raw.get("url")),
        value=_text(raw.get("value")),
        key=_text(raw.get("key")),
        reason=_text(raw.get("reason")),
    )


def validate_decision(decision: AgentDecision, observed_refs: set[str], allowed_hosts: set[str]) -> list[str]:
    errors: list[str] = []
    if decision.action in REF_ACTIONS and decision.ref not in observed_refs:
        errors.append(f"unknown ref: {decision.ref or 'empty'}")
    if decision.action == "goto":
        parsed = urlparse(decision.url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            errors.append("goto requires absolute http(s) url")
        elif parsed.hostname not in allowed_hosts:
            errors.append(f"host not allowed: {parsed.hostname}")
    return errors
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest codex-chrome-smoke/runner/tests/test_agent_actions.py -v`

Expected: PASS.

### Task 2: Agent Goal Builder and Host Whitelist

**Files:**
- Create: `codex-chrome-smoke/runner/agent_explore.py`
- Test: `codex-chrome-smoke/runner/tests/test_agent_explore_goal.py`

- [ ] **Step 1: Write failing tests**

```python
from runner.agent_explore import allowed_hosts_for_system, build_agent_goal


def test_allowed_hosts_from_system_urls():
    system = {"base_url": "https://icm.example.test/app", "entry_url": "https://icm.example.test/#/login"}
    assert allowed_hosts_for_system(system) == {"icm.example.test"}


def test_build_goal_includes_case_steps_and_expected_results():
    case = {
        "id": "TC-ICM-999",
        "title": "Open device list",
        "steps": ["Open homepage", "Open device list"],
        "expected_results": ["Device list is visible"],
    }
    goal = build_agent_goal(case)
    assert "TC-ICM-999" in goal
    assert "Open device list" in goal
    assert "Device list is visible" in goal
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest codex-chrome-smoke/runner/tests/test_agent_explore_goal.py -v`

Expected: FAIL because `runner.agent_explore` does not exist.

- [ ] **Step 3: Implement goal and whitelist helpers**

```python
from __future__ import annotations

from urllib.parse import urlparse


def allowed_hosts_for_system(system: dict) -> set[str]:
    hosts: set[str] = set()
    for key in ("base_url", "entry_url", "login_url"):
        value = str(system.get(key) or "")
        if value:
            parsed = urlparse(value)
            if parsed.hostname:
                hosts.add(parsed.hostname)
    return hosts


def build_agent_goal(case: dict) -> str:
    lines = [
        f"Case ID: {case.get('id', '')}",
        f"Title: {case.get('title', '')}",
        "Steps:",
    ]
    lines.extend(f"- {step}" for step in case.get("steps") or [])
    lines.append("Expected results:")
    lines.extend(f"- {item}" for item in case.get("expected_results") or [])
    asset = case.get("automation_asset") or {}
    if asset.get("operation_steps"):
        lines.append("Automation operation steps:")
        lines.extend(f"- {step}" for step in asset["operation_steps"])
    return "\n".join(line for line in lines if line is not None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest codex-chrome-smoke/runner/tests/test_agent_explore_goal.py -v`

Expected: PASS.

### Task 3: Agent Page Observation

**Files:**
- Modify: `codex-chrome-smoke/runner/agent_explore.py`
- Test: `codex-chrome-smoke/runner/tests/test_agent_explore_observe.py`

- [ ] **Step 1: Write failing async test**

```python
import pytest
from playwright.async_api import async_playwright

from runner.agent_explore import observe_page


@pytest.mark.asyncio
async def test_observe_page_returns_refs(tmp_path):
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content("<button id='go'>Go</button><input placeholder='Name' />")
        observation = await observe_page(page)
        await browser.close()
    refs = [item["ref"] for item in observation["interactives"]]
    assert refs == ["e1", "e2"]
    assert observation["interactives"][0]["selector"] == "#go"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest codex-chrome-smoke/runner/tests/test_agent_explore_observe.py -v`

Expected: FAIL because `observe_page` does not exist.

- [ ] **Step 3: Implement `observe_page`**

```python
async def observe_page(page) -> dict:
    return await page.evaluate(
        """() => {
          const visible = (el) => {
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
          };
          const esc = (value) => window.CSS && CSS.escape ? CSS.escape(value) : String(value).replace(/["\\\\#.;?+*~':!^$[\\]()=>|/@]/g, "\\\\$&");
          const selectorFor = (el) => {
            if (el.id) return `#${esc(el.id)}`;
            const testId = el.getAttribute('data-testid') || el.getAttribute('data-test');
            if (testId) return `[data-testid="${esc(testId)}"],[data-test="${esc(testId)}"]`;
            const name = el.getAttribute('name');
            if (name) return `${el.tagName.toLowerCase()}[name="${esc(name)}"]`;
            const placeholder = el.getAttribute('placeholder');
            if (placeholder) return `${el.tagName.toLowerCase()}[placeholder="${esc(placeholder)}"]`;
            return el.tagName.toLowerCase();
          };
          const textOf = (el) => (el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('placeholder') || '').replace(/\\s+/g, ' ').trim().slice(0, 120);
          const interactives = Array.from(document.querySelectorAll('a,button,input,textarea,select,[role="button"],[role="link"],[contenteditable="true"]'))
            .filter(visible)
            .slice(0, 45)
            .map((el, index) => ({
              ref: `e${index + 1}`,
              tag: el.tagName.toLowerCase(),
              type: el.getAttribute('type') || '',
              text: textOf(el),
              placeholder: el.getAttribute('placeholder') || '',
              selector: selectorFor(el),
            }));
          const visibleText = (document.body && document.body.innerText || '').split(/\\n+/).map((line) => line.replace(/\\s+/g, ' ').trim()).filter(Boolean).slice(0, 35);
          return { url: location.href, title: document.title, visibleText, interactives };
        }"""
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest codex-chrome-smoke/runner/tests/test_agent_explore_observe.py -v`

Expected: PASS.

### Task 4: Candidate Flow Generation

**Files:**
- Create: `codex-chrome-smoke/runner/agent_codegen.py`
- Test: `codex-chrome-smoke/runner/tests/test_agent_codegen.py`

- [ ] **Step 1: Write failing test**

```python
from runner.agent_codegen import generate_candidate_flow


def test_generate_candidate_flow_uses_existing_helpers():
    trace = {
        "case_id": "TC-ICM-999",
        "history": [
            {"decision": {"action": "goto", "url": "https://icm.example.test/#/index"}},
            {"decision": {"action": "fill", "ref": "e1", "value": "admin"}, "execution": {"selector": "input[name=\\"username\\"]"}},
            {"decision": {"action": "click", "ref": "e2"}, "execution": {"selector": "button[type=\\"submit\\"]"}},
            {"decision": {"action": "assert_text", "value": "首页"}},
        ],
    }
    code = generate_candidate_flow(trace)
    assert "async def run(page, system, case)" in code
    assert "fill_first(page, ['input[name=\"username\"]'], 'admin')" in code
    assert "click_first(page, ['button[type=\"submit\"]'])" in code
    assert "ensure_text_visible(page, '首页')" in code
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest codex-chrome-smoke/runner/tests/test_agent_codegen.py -v`

Expected: FAIL because `runner.agent_codegen` does not exist.

- [ ] **Step 3: Implement minimal generator**

```python
from __future__ import annotations

from reprlib import repr as safe_repr


def _quote(value: str) -> str:
    return repr(str(value))


def generate_candidate_flow(trace: dict) -> str:
    lines = [
        "from __future__ import annotations",
        "",
        "from runner.browser import click_first, ensure_text_visible, fill_first, goto_route",
        "",
        "",
        "async def run(page, system, case) -> None:",
        "    # Generated from successful Agent exploration. Review before registration.",
    ]
    for item in trace.get("history") or []:
        decision = item.get("decision") or {}
        execution = item.get("execution") or {}
        action = decision.get("action")
        selector = execution.get("selector")
        if action == "goto" and decision.get("url"):
            lines.append(f"    await page.goto({_quote(decision['url'])}, wait_until='domcontentloaded')")
        elif action == "fill" and selector:
            lines.append(f"    await fill_first(page, [{_quote(selector)}], {_quote(decision.get('value', ''))})")
        elif action == "click" and selector:
            lines.append(f"    await click_first(page, [{_quote(selector)}])")
        elif action == "assert_text" and decision.get("value"):
            lines.append(f"    await ensure_text_visible(page, {_quote(decision['value'])})")
    if len(lines) == 7:
        lines.append("    raise RuntimeError('Agent trace did not contain executable actions')")
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest codex-chrome-smoke/runner/tests/test_agent_codegen.py -v`

Expected: PASS.

### Task 5: Runner Command Integration

**Files:**
- Modify: `codex-chrome-smoke/runner/main.py`
- Test: `codex-chrome-smoke/runner/tests/test_main_agent_explore_args.py`

- [ ] **Step 1: Write failing test**

```python
from runner.main import parse_args


def test_parse_agent_explore_command():
    args = parse_args(["agent-explore", "TC-ICM-001", "run-1"])
    assert args.command == "agent-explore"
    assert args.arg == "TC-ICM-001"
    assert args.run_id == "run-1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest codex-chrome-smoke/runner/tests/test_main_agent_explore_args.py -v`

Expected: FAIL because parser choices do not include `agent-explore`.

- [ ] **Step 3: Add parser choice and dispatch stub**

Change `choices=["run-case", "run-batch", "run-draft"]` to include `agent-explore`. In `main()`, add a branch after `run-draft`:

```python
        elif args.command == "agent-explore":
            from runner.agent_explore import run_agent_explore

            run_id = args.run_id or f"{datetime.now():%Y%m%d-%H%M}-agent-explore"
            result = await run_agent_explore(session.page, run_id, args.arg)
            if result["status"] != "passed":
                exit_status = 1
```

- [ ] **Step 4: Run parser test**

Run: `python -m pytest codex-chrome-smoke/runner/tests/test_main_agent_explore_args.py -v`

Expected: PASS.

### Task 6: Worker and API Mode Wiring

**Files:**
- Modify: `codex-chrome-smoke/icm_platform/worker.py`
- Modify: `codex-chrome-smoke/icm_platform/api.py`
- Test: `codex-chrome-smoke/icm_platform/tests/test_worker_agent_explore.py`

- [ ] **Step 1: Write failing tests**

```python
import pytest

from icm_platform.worker import RunnerWorker


def test_worker_accepts_agent_explore_mode_validation():
    worker = RunnerWorker()
    with pytest.raises(ValueError):
        worker.enqueue("bad-mode", case_id="TC-ICM-001")
```

This keeps the existing bad-mode behavior while the implementation adds `agent-explore` to the allowed set. Use existing API tests to check the `RunRequest` literal if present.

- [ ] **Step 2: Run focused tests**

Run: `python -m pytest codex-chrome-smoke/icm_platform/tests/test_worker_agent_explore.py -v`

Expected: existing behavior passes after test file imports; before wiring, manual review shows `agent-explore` is rejected.

- [ ] **Step 3: Add `agent-explore` mode**

In `RunnerWorker.enqueue`, change allowed modes to:

```python
{"run-case", "run-batch", "run-draft", "agent-explore"}
```

For `agent-explore`, require `case_id`, set `arg = case_id`, and append `platform_run_id` like `run-case`.

In `_run`, add:

```python
        if task["mode"] == "agent-explore":
            command.extend([task["case_id"], task["id"]])
```

before the existing `run-case` branch or by using a small command argument map.

In `api.py`, extend `RunRequest.mode` to:

```python
Literal["run-case", "run-batch", "run-draft", "agent-explore"]
```

- [ ] **Step 4: Run API/worker tests**

Run: `python -m pytest codex-chrome-smoke/icm_platform/tests/test_worker_agent_explore.py codex-chrome-smoke/icm_platform/tests/test_api_stability.py -v`

Expected: PASS.

### Task 7: Full Agent Explore Loop

**Files:**
- Modify: `codex-chrome-smoke/runner/agent_explore.py`
- Modify: `codex-chrome-smoke/runner/agent_actions.py`
- Test: `codex-chrome-smoke/runner/tests/test_agent_explore_loop.py`

- [ ] **Step 1: Write tests using a fake decider**

```python
import pytest

from runner.agent_explore import run_agent_loop


@pytest.mark.asyncio
async def test_agent_loop_stops_on_finish():
    calls = []

    async def observe():
        return {"url": "http://127.0.0.1", "title": "", "visibleText": ["Done"], "interactives": []}

    async def decide(goal, observation, history, step_index, max_steps):
        calls.append(step_index)
        return {"action": "finish", "reason": "done"}

    result = await run_agent_loop(
        goal="finish when done",
        observe=observe,
        decide=decide,
        execute=lambda decision, observation: None,
        allowed_hosts={"127.0.0.1"},
        max_steps=3,
    )
    assert result["ok"] is True
    assert result["history"][0]["decision"]["action"] == "finish"
    assert calls == [0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest codex-chrome-smoke/runner/tests/test_agent_explore_loop.py -v`

Expected: FAIL because `run_agent_loop` does not exist.

- [ ] **Step 3: Implement loop with injectable functions**

Implement `run_agent_loop` so unit tests can pass fake `observe`, `decide`, and `execute`. The production `run_agent_explore` should call it with Playwright-backed functions and write `trace.json`.

- [ ] **Step 4: Run loop tests**

Run: `python -m pytest codex-chrome-smoke/runner/tests/test_agent_explore_loop.py -v`

Expected: PASS.

### Task 8: Verification

**Files:**
- No new files.

- [ ] **Step 1: Run focused Python tests**

Run: `python -m pytest codex-chrome-smoke/runner/tests/test_agent_actions.py codex-chrome-smoke/runner/tests/test_agent_explore_goal.py codex-chrome-smoke/runner/tests/test_agent_codegen.py codex-chrome-smoke/runner/tests/test_main_agent_explore_args.py -v`

Expected: PASS.

- [ ] **Step 2: Run existing runner tests**

Run: `python -m pytest codex-chrome-smoke/runner/tests -v`

Expected: PASS.

- [ ] **Step 3: Run existing platform tests likely affected by API/worker changes**

Run: `python -m pytest codex-chrome-smoke/icm_platform/tests/test_api_stability.py codex-chrome-smoke/icm_platform/tests/test_run_views.py -v`

Expected: PASS.

- [ ] **Step 4: Build frontend only if UI wiring is added in this iteration**

Run: `cmd /c npm run build` from `codex-chrome-smoke/web-ui`

Expected: build succeeds.

## Self-Review

- Spec coverage: plan covers sidecar command, goal building, whitelist, action safety, page observation, trace-driven code generation, worker/API wiring, and verification.
- Placeholder scan: no implementation step relies on an undefined placeholder.
- Type consistency: `AgentDecision`, `run_agent_loop`, `run_agent_explore`, and `generate_candidate_flow` names are consistent across tasks.
