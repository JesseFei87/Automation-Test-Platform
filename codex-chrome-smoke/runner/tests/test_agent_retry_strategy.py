import asyncio
import json

from runner.agent_actions import normalize_decision
from runner.agent_explore import execute_agent_decision


def test_execute_agent_decision_retries_click_after_healing_scroll(tmp_path, monkeypatch):
    feedback_path = tmp_path / "feedback.json"
    monkeypatch.setenv("ELEMENT_FEEDBACK_PATH", str(feedback_path))
    monkeypatch.setenv("ELEMENT_FEEDBACK_ENABLED", "1")

    class Locator:
        def __init__(self):
            self.clicks = 0
            self.scrolled = False

        async def click(self, timeout):
            self.clicks += 1
            if self.clicks == 1:
                raise RuntimeError("Agent target is not visible")

        async def scroll_into_view_if_needed(self, timeout):
            self.scrolled = timeout == 5000

    class Page:
        def __init__(self):
            self.waits = []

        async def wait_for_timeout(self, ms):
            self.waits.append(ms)

    locator = Locator()

    async def fake_first_visible(page, candidates):
        return locator

    monkeypatch.setattr("runner.agent_explore.first_visible", fake_first_visible)
    decision = normalize_decision({"action": "click", "ref": "e1", "reason": "click create"})
    observation = {
        "url": "http://localhost:5173/#/users",
        "interactives": [
            {
                "ref": "e1",
                "selector": "button.add",
                "text": "新增用户",
                "healing_issue": "target_not_visible",
                "element_id": "users.create_button",
            }
        ],
    }

    result = asyncio.run(execute_agent_decision(Page(), decision, observation))

    assert result["result"] == "clicked"
    assert result["healing_retry"] == ["scroll_into_view", "wait_after_scroll"]
    assert locator.clicks == 2
    assert locator.scrolled is True
    feedback = json.loads(feedback_path.read_text(encoding="utf-8"))
    assert next(iter(feedback["stats"].values()))["success"] == 1


def test_execute_agent_decision_keeps_failure_when_retry_fails(tmp_path, monkeypatch):
    feedback_path = tmp_path / "feedback.json"
    monkeypatch.setenv("ELEMENT_FEEDBACK_PATH", str(feedback_path))
    monkeypatch.setenv("ELEMENT_FEEDBACK_ENABLED", "1")

    class Locator:
        async def click(self, timeout):
            raise RuntimeError("Agent target is not visible")

        async def scroll_into_view_if_needed(self, timeout):
            pass

    class Page:
        async def wait_for_timeout(self, ms):
            pass

    async def fake_first_visible(page, candidates):
        return Locator()

    monkeypatch.setattr("runner.agent_explore.first_visible", fake_first_visible)
    decision = normalize_decision({"action": "click", "ref": "e1", "reason": "click create"})
    observation = {
        "url": "http://localhost:5173/#/users",
        "interactives": [{"ref": "e1", "selector": "button.add", "healing_issue": "target_not_visible"}],
    }

    try:
        asyncio.run(execute_agent_decision(Page(), decision, observation))
    except RuntimeError as exc:
        assert "not visible" in str(exc)
    else:
        raise AssertionError("expected retry failure")

    feedback = json.loads(feedback_path.read_text(encoding="utf-8"))
    assert feedback["records"][0]["success"] is False
    assert "not visible" in feedback["records"][0]["error"]
