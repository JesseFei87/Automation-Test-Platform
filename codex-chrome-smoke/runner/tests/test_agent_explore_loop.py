import asyncio
import json

from runner.agent_actions import normalize_decision
from runner.agent_explore import OBSERVE_PAGE_SCRIPT, _agent_decision_payload, build_agent_prompt, execute_agent_decision, extract_json_object, run_agent_loop


def test_agent_loop_stops_on_finish():
    async def scenario():
        calls = []

        async def observe():
            return {"url": "http://127.0.0.1", "title": "", "visibleText": ["Done"], "interactives": []}

        async def decide(goal, observation, history, step_index, max_steps):
            calls.append(step_index)
            return {"action": "finish", "reason": "done"}

        async def execute(decision, observation):
            return {"result": "not-called"}

        result = await run_agent_loop(
            goal="finish when done",
            observe=observe,
            decide=decide,
            execute=execute,
            allowed_hosts={"127.0.0.1"},
            max_steps=3,
        )
        assert result["ok"] is True
        assert result["history"][0]["decision"]["action"] == "finish"
        assert calls == [0]

    asyncio.run(scenario())


def test_agent_loop_publishes_each_recorded_step():
    async def scenario():
        snapshots = []

        async def observe():
            return {"url": "http://127.0.0.1", "visibleText": [], "interactives": []}

        async def decide(goal, observation, history, step_index, max_steps):
            return {"action": "finish", "reason": "done"}

        result = await run_agent_loop(
            "finish",
            observe,
            decide,
            lambda decision, observation: None,
            {"127.0.0.1"},
            on_history=lambda history: snapshots.append(list(history)),
        )

        assert result["ok"] is True
        assert len(snapshots) == 1
        assert snapshots[0][0]["decision"]["action"] == "finish"

    asyncio.run(scenario())


def test_agent_loop_attaches_element_knowledge_evidence(monkeypatch):
    async def scenario():
        async def observe():
            return {"url": "https://example.test/#/users", "interactives": [{"ref": "e3", "text": "新增用户"}]}

        async def decide(goal, observation, history, step_index, max_steps):
            return {"action": "click", "ref": "e3", "reason": "新增用户"}

        async def execute(decision, observation):
            return {"result": "clicked"}

        monkeypatch.setattr(
            "runner.agent_explore.build_agent_ref_evidence",
            lambda *args, **kwargs: {
                "matched": True,
                "candidate_count": 1,
                "candidates": [{"element_id": "create", "recommended_ref": "e3"}],
                "selected_ref": "e3",
                "adopted": True,
                "adopted_element_id": "create",
            },
        )
        result = await run_agent_loop("新增用户", observe, decide, execute, {"example.test"}, max_steps=1)

        assert result["history"][0]["element_knowledge"]["adopted"] is True
        assert result["history"][0]["element_knowledge"]["selected_ref"] == "e3"

    asyncio.run(scenario())


def test_agent_loop_stops_on_execution_error():
    async def scenario():
        async def observe():
            return {
                "url": "http://127.0.0.1",
                "title": "",
                "visibleText": [],
                "interactives": [{"ref": "e1", "selector": "#go"}],
            }

        async def decide(goal, observation, history, step_index, max_steps):
            return {"action": "click", "ref": "e1", "reason": "click"}

        async def execute(decision, observation):
            return {"result": "error", "error": "click failed"}

        result = await run_agent_loop(
            goal="click once",
            observe=observe,
            decide=decide,
            execute=execute,
            allowed_hosts={"127.0.0.1"},
            max_steps=3,
        )
        assert result["ok"] is False
        assert result["error"] == "click failed"
        assert len(result["history"]) == 1

    asyncio.run(scenario())


def test_agent_loop_recovers_unknown_ref_with_fresh_bound_ref(monkeypatch):
    async def scenario():
        observations = [
            {"url": "https://example.test/#/users", "interactives": [{"ref": "e1", "selector": "button.old"}]},
            {"url": "https://example.test/#/users", "interactives": [{"ref": "e2", "selector": "button.add", "text": "新增"}]},
        ]
        observed = {"count": 0}
        executed = []

        async def observe():
            index = min(observed["count"], len(observations) - 1)
            observed["count"] += 1
            return observations[index]

        async def decide(goal, observation, history, step_index, max_steps):
            return {"action": "click", "ref": "missing" if step_index == 0 else "", "reason": "新增用户"} if step_index == 0 else {"action": "finish", "reason": "done"}

        async def execute(decision, observation):
            executed.append(decision.ref)
            return {"result": "clicked", "ref": decision.ref}

        monkeypatch.setattr(
            "runner.agent_explore.resolve_recovery_ref",
            lambda *args, **kwargs: {"status": "resolved", "ref": "e2", "score": 40.0, "element_name": "user_create_button"},
        )
        result = await run_agent_loop("新增用户", observe, decide, execute, {"example.test"}, max_steps=2)

        assert result["ok"] is True
        assert executed == ["e2"]
        assert result["history"][0]["execution"]["recovery"]["original_ref"] == "missing"
        assert result["history"][0]["decision"]["ref"] == "e2"

    asyncio.run(scenario())


def test_agent_loop_does_not_retry_after_action_timeout(monkeypatch):
    async def scenario():
        calls = {"resolver": 0, "execute": 0}

        async def observe():
            return {"url": "https://example.test/#/users", "interactives": [{"ref": "e1", "selector": "button.add"}]}

        async def decide(goal, observation, history, step_index, max_steps):
            return {"action": "click", "ref": "e1", "reason": "新增用户"}

        async def execute(decision, observation):
            calls["execute"] += 1
            return {"result": "error", "error": "timeout after click dispatched"}

        def resolve(*args, **kwargs):
            calls["resolver"] += 1
            return {"status": "resolved", "ref": "e2", "score": 40.0}

        monkeypatch.setattr("runner.agent_explore.resolve_recovery_ref", resolve)
        result = await run_agent_loop("新增用户", observe, decide, execute, {"example.test"}, max_steps=2)

        assert result["ok"] is False
        assert calls == {"resolver": 0, "execute": 1}

    asyncio.run(scenario())


def test_agent_loop_rejects_rebound_ref_outside_fresh_observation(monkeypatch):
    async def scenario():
        executed = []

        async def observe():
            return {"url": "https://example.test/#/users", "interactives": [{"ref": "e2", "selector": "button.add"}]}

        async def decide(goal, observation, history, step_index, max_steps):
            return {"action": "click", "ref": "missing", "reason": "新增用户"}

        async def execute(decision, observation):
            executed.append(decision.ref)
            return {"result": "clicked"}

        monkeypatch.setattr(
            "runner.agent_explore.resolve_recovery_ref",
            lambda *args, **kwargs: {"status": "resolved", "ref": "e9", "score": 40.0},
        )
        result = await run_agent_loop("新增用户", observe, decide, execute, {"example.test"}, max_steps=1)

        assert result["ok"] is False
        assert executed == []
        assert result["history"][0]["execution"]["recovery"]["status"] == "invalid_rebound_ref"

    asyncio.run(scenario())


def test_agent_loop_does_not_execute_same_action_twice_when_page_is_unchanged():
    async def scenario():
        executed_refs = []

        async def observe():
            return {
                "url": "https://example.test/#/index",
                "title": "ICM",
                "visibleText": ["首页"],
                "interactives": [
                    {"ref": "e1", "selector": "#home", "text": "首页"},
                    {"ref": "e2", "selector": "#device", "text": "设备信息"},
                ],
            }

        async def decide(goal, observation, history, step_index, max_steps):
            if step_index < 2:
                return {"action": "click", "ref": "e1", "reason": "open menu"}
            if step_index == 2:
                assert history[-1]["execution"]["result"] == "duplicate_action_blocked"
                return {"action": "click", "ref": "e2", "reason": "try device menu"}
            return {"action": "finish", "reason": "device page opened"}

        async def execute(decision, observation):
            executed_refs.append(decision.ref)
            return {"result": "clicked", "ref": decision.ref}

        result = await run_agent_loop(
            goal="open device page",
            observe=observe,
            decide=decide,
            execute=execute,
            allowed_hosts={"example.test"},
            max_steps=4,
        )

        assert result["ok"] is True
        assert executed_refs == ["e1", "e2"]

    asyncio.run(scenario())


def test_agent_loop_finishes_when_success_signal_exists_before_empty_ref_error():
    async def scenario():
        responses = [
            {
                "url": "https://example.test/login",
                "title": "",
                "visibleText": ["登录"],
                "interactives": [{"ref": "e1", "selector": "#user"}],
            },
            {
                "url": "https://example.test/#/icm",
                "title": "",
                "visibleText": ["test", "屏幕墙"],
                "interactives": [{"ref": "e1", "selector": "#profile", "text": "test"}],
            },
        ]
        calls = {"count": 0}

        async def observe():
            index = min(calls["count"], len(responses) - 1)
            return responses[index]

        async def decide(goal, observation, history, step_index, max_steps):
            calls["count"] += 1
            if step_index == 0:
                return {"action": "wait", "reason": "login settles"}
            return {"action": "click", "ref": "", "reason": "extra tail action"}

        async def execute(decision, observation):
            return {"result": "waited"}

        result = await run_agent_loop(
            goal="Case ID: LOGIN_FUN_003\nPrecondition: 已通过 test/123456 成功登录\nTest data: username=test, password=123456",
            observe=observe,
            decide=decide,
            execute=execute,
            allowed_hosts={"example.test"},
            max_steps=3,
        )
        assert result["ok"] is True
        assert result["history"][-1]["decision"]["action"] == "finish"

    asyncio.run(scenario())


def test_extract_json_object_rejects_unterminated_string():
    try:
        extract_json_object('{"action":"click","reason":"broken')
    except ValueError as exc:
        assert "Unterminated string" in str(exc)
    else:
        raise AssertionError("unterminated JSON should be rejected")


def test_extract_json_object_strips_think_and_fence():
    parsed = extract_json_object('<think>plan</think>\n```json\n{"action":"wait","reason":"settle"}\n```')
    assert parsed == {"action": "wait", "reason": "settle"}


def test_agent_decision_payload_uses_minimax_completion_tokens():
    payload = _agent_decision_payload("MiniMax-M3", "minimax-m3", "do it")
    assert payload["stream"] is False
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["max_completion_tokens"] == 1200
    assert "max_tokens" not in payload


def test_agent_prompt_advertises_hover_action():
    prompt = build_agent_prompt("hover more", {"interactives": []}, [], 0, 3)

    assert "hover" in prompt.split("Allowed actions:", 1)[1].splitlines()[0]


def test_execute_agent_decision_uses_playwright_hover(monkeypatch):
    class Locator:
        def __init__(self):
            self.hovered = False

        async def hover(self, timeout):
            self.hovered = timeout == 8000

    locator = Locator()

    async def fake_first_visible(page, candidates):
        assert candidates == ["#more", "text=更多"]
        return locator

    monkeypatch.setattr("runner.agent_explore.first_visible", fake_first_visible)
    decision = normalize_decision({"action": "hover", "ref": "e1", "reason": "reveal menu"})
    observation = {"interactives": [{"ref": "e1", "selector": "#more", "text": "更多"}]}

    result = asyncio.run(execute_agent_decision(object(), decision, observation))

    assert result["result"] == "hovered"
    assert locator.hovered is True


def test_execute_agent_decision_retries_hover_after_dismissing_stale_dropdown(monkeypatch):
    class Locator:
        def __init__(self):
            self.calls = 0

        async def hover(self, timeout):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("subtree intercepts pointer events")
            assert timeout == 8000

    class Mouse:
        def __init__(self):
            self.moves = []

        async def move(self, x, y):
            self.moves.append((x, y))

    class Keyboard:
        def __init__(self):
            self.presses = []

        async def press(self, key):
            self.presses.append(key)

    class Page:
        def __init__(self):
            self.mouse = Mouse()
            self.keyboard = Keyboard()
            self.waits = []

        async def wait_for_timeout(self, ms):
            self.waits.append(ms)

    locator = Locator()
    page = Page()

    async def fake_first_visible(page, candidates):
        return locator

    monkeypatch.setattr("runner.agent_explore.first_visible", fake_first_visible)
    decision = normalize_decision({"action": "hover", "ref": "e1", "reason": "reveal menu"})
    observation = {"interactives": [{"ref": "e1", "selector": "#more", "text": "更多"}]}

    result = asyncio.run(execute_agent_decision(page, decision, observation))

    assert result["result"] == "hovered"
    assert locator.calls == 2
    assert page.keyboard.presses == ["Escape"]
    assert page.mouse.moves == [(1, 1)]
    assert page.waits == [120]


def test_observe_page_script_collects_dropdown_menu_items():
    assert ".el-dropdown-menu__item" in OBSERVE_PAGE_SCRIPT
    assert 'img[tabindex]:not([tabindex="-1"])' in OBSERVE_PAGE_SCRIPT
    assert "aria-describedby" in OBSERVE_PAGE_SCRIPT
    assert ".top_button > img.el-tooltip.button:nth-of-type" in OBSERVE_PAGE_SCRIPT


def test_execute_agent_decision_treats_visible_dropdown_intercept_as_open_menu(monkeypatch):
    class Locator:
        async def click(self, timeout):
            raise RuntimeError("subtree intercepts pointer events")

    class CountLocator:
        async def count(self):
            return 1

    class DropdownLocator:
        def locator(self, selector):
            assert selector == ":visible"
            return CountLocator()

    class Page:
        def locator(self, selector):
            assert selector == ".el-dropdown-menu__item"
            return DropdownLocator()

    locator = Locator()
    page = Page()

    async def fake_first_visible(page, candidates):
        assert candidates == ["tr:nth-of-type(3) > td:nth-of-type(9) > div > div > button", "text=更多"]
        return locator

    monkeypatch.setattr("runner.agent_explore.first_visible", fake_first_visible)
    decision = normalize_decision({"action": "click", "ref": "e1", "reason": "open more menu"})
    observation = {
        "interactives": [
            {
                "ref": "e1",
                "selector": "tr:nth-of-type(3) > td:nth-of-type(9) > div > div > button",
                "text": "更多",
                "ariaLabel": "",
            }
        ]
    }

    result = asyncio.run(execute_agent_decision(page, decision, observation))

    assert result["result"] == "dropdown_opened"


def test_agent_loop_preserves_history_when_decision_raises():
    async def scenario():
        calls = {"count": 0}

        async def observe():
            return {
                "url": "http://127.0.0.1",
                "title": "",
                "visibleText": ["Ready"],
                "interactives": [{"ref": "e1", "selector": "#go"}],
            }

        async def decide(goal, observation, history, step_index, max_steps):
            calls["count"] += 1
            if calls["count"] == 1:
                return {"action": "wait", "reason": "settle"}
            raise ValueError("AI response JSON parse failed: empty content after cleanup")

        async def execute(decision, observation):
            return {"result": "waited"}

        result = await run_agent_loop(
            goal="click once",
            observe=observe,
            decide=decide,
            execute=execute,
            allowed_hosts={"127.0.0.1"},
            max_steps=3,
        )
        assert result["ok"] is False
        assert len(result["history"]) == 2
        assert result["history"][0]["decision"]["action"] == "wait"
        assert result["history"][1]["decision"]["action"] == "fail"

    asyncio.run(scenario())


def test_agent_loop_continues_when_login_precondition_already_satisfied():
    async def scenario():
        calls = {"count": 0}

        async def observe():
            return {
                "url": "https://example.test/#/index",
                "title": "ICM",
                "visibleText": ["首页"],
                "interactives": [{"ref": "e1", "selector": "#menu", "text": "设备信息"}],
            }

        async def decide(goal, observation, history, step_index, max_steps):
            calls["count"] += 1
            if calls["count"] == 1:
                return {
                    "action": "fail",
                    "reason": "Already on home page (index). The login form is not visible because of pre-existing session.",
                }
            return {"action": "finish", "reason": "continued after login precondition"}

        async def execute(decision, observation):
            return {"result": "not-called"}

        result = await run_agent_loop(
            goal="Case ID: ICMDEV_FUN_001\nSteps:\n- 1. login\n- 2. open device page",
            observe=observe,
            decide=decide,
            execute=execute,
            allowed_hosts={"example.test"},
            max_steps=3,
        )
        assert result["ok"] is True
        assert result["history"][0]["execution"]["result"] == "login_precondition_satisfied"
        assert result["history"][1]["decision"]["action"] == "finish"

    asyncio.run(scenario())


def test_agent_loop_ignores_finish_when_only_login_is_satisfied():
    async def scenario():
        calls = {"count": 0}

        async def observe():
            return {
                "url": "https://example.test/#/index",
                "title": "ICM",
                "visibleText": ["首页"],
                "interactives": [{"ref": "e1", "selector": "#menu", "text": "设备信息"}],
            }

        async def decide(goal, observation, history, step_index, max_steps):
            calls["count"] += 1
            if calls["count"] == 1:
                return {"action": "finish", "reason": "Login already completed on home page"}
            return {"action": "finish", "reason": "business steps complete"}

        async def execute(decision, observation):
            return {"result": "not-called"}

        result = await run_agent_loop(
            goal="Case ID: ICMDEV_FUN_001\nSteps:\n- 1. login\n- 2. open device page\n- 3. click add",
            observe=observe,
            decide=decide,
            execute=execute,
            allowed_hosts={"example.test"},
            max_steps=3,
        )
        assert result["ok"] is True
        assert result["history"][0]["execution"]["result"] == "login_precondition_satisfied"
        assert result["history"][1]["decision"]["reason"] == "business steps complete"

    asyncio.run(scenario())


def test_agent_loop_retries_decide_on_network_provider_error():
    """B 方案：step_index>0 时，AI provider 网络错误重试一次，成功则继续。"""
    async def scenario():
        calls = {"count": 0}

        class _FakeAIProviderError(Exception):
            pass

        async def observe():
            return {"url": "http://127.0.0.1", "title": "", "visibleText": ["Ready"], "interactives": []}

        async def decide(goal, observation, history, step_index, max_steps):
            calls["count"] += 1
            if calls["count"] == 1:
                return {"action": "wait", "reason": "settle"}
            if calls["count"] == 2:
                # 模拟网络错误（类名为 AIProviderError）
                raise _FakeAIProviderError("模型网络连接失败：[Errno 2] No such file or directory")
            return {"action": "finish", "reason": "done after retry"}

        async def execute(decision, observation):
            return {"result": "waited"}

        # monkeypatch _is_network_provider_error 让 _FakeAIProviderError 被识别
        import runner.agent_explore as ae
        original = ae._is_network_provider_error
        ae._is_network_provider_error = lambda exc: type(exc).__name__ in ("AIProviderError", "_FakeAIProviderError")
        try:
            result = await run_agent_loop(
                goal="settle then finish",
                observe=observe,
                decide=decide,
                execute=execute,
                allowed_hosts={"127.0.0.1"},
                max_steps=3,
            )
        finally:
            ae._is_network_provider_error = original

        assert result["ok"] is True
        assert calls["count"] == 3
        assert result["history"][0]["decision"]["action"] == "wait"
        assert result["history"][1]["decision"]["action"] == "finish"

    asyncio.run(scenario())


def test_agent_loop_does_not_retry_on_value_error():
    """B 方案：ValueError（JSON 解析错误）不重试，直接失败。保护现有行为。"""
    async def scenario():
        calls = {"count": 0}

        async def observe():
            return {"url": "http://127.0.0.1", "title": "", "visibleText": ["Ready"], "interactives": []}

        async def decide(goal, observation, history, step_index, max_steps):
            calls["count"] += 1
            if calls["count"] == 1:
                return {"action": "wait", "reason": "settle"}
            raise ValueError("JSON parse failed")

        async def execute(decision, observation):
            return {"result": "waited"}

        result = await run_agent_loop(
            goal="settle then fail",
            observe=observe,
            decide=decide,
            execute=execute,
            allowed_hosts={"127.0.0.1"},
            max_steps=3,
        )
        assert result["ok"] is False
        assert calls["count"] == 2
        assert len(result["history"]) == 2
        assert result["history"][1]["decision"]["action"] == "fail"

    asyncio.run(scenario())
