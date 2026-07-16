import asyncio
import json

from runner.agent_actions import normalize_decision
from runner.agent_explore import execute_agent_decision


def test_execute_agent_decision_records_success_feedback(tmp_path, monkeypatch):
    feedback_path = tmp_path / "feedback.json"
    monkeypatch.setenv("ELEMENT_FEEDBACK_PATH", str(feedback_path))
    monkeypatch.setenv("ELEMENT_FEEDBACK_ENABLED", "1")

    class Locator:
        async def click(self, timeout):
            assert timeout == 8000

    async def fake_first_visible(page, candidates):
        assert candidates == ["button.add", "text=新增用户"]
        return Locator()

    monkeypatch.setattr("runner.agent_explore.first_visible", fake_first_visible)
    decision = normalize_decision({"action": "click", "ref": "e1", "reason": "create user"})
    observation = {
        "url": "http://localhost:5173/#/users",
        "interactives": [
            {
                "ref": "e1",
                "selector": "button.add",
                "text": "新增用户",
                "element_id": "users.create_button",
                "page_id": "users",
                "state": "default",
            }
        ],
    }

    result = asyncio.run(execute_agent_decision(object(), decision, observation))

    assert result["result"] == "clicked"
    payload = json.loads(feedback_path.read_text(encoding="utf-8"))
    record = payload["records"][0]
    assert record["element_id"] == "users.create_button"
    assert record["action"] == "click"
    assert record["selector"] == "button.add"
    assert record["success"] is True
    assert payload["stats"]["users.create_button"]["success_rate"] == 1.0


def test_execute_agent_decision_records_failure_feedback(tmp_path, monkeypatch):
    feedback_path = tmp_path / "feedback.json"
    monkeypatch.setenv("ELEMENT_FEEDBACK_PATH", str(feedback_path))
    monkeypatch.setenv("ELEMENT_FEEDBACK_ENABLED", "1")

    async def fake_first_visible(page, candidates):
        return None

    monkeypatch.setattr("runner.agent_explore.first_visible", fake_first_visible)
    decision = normalize_decision({"action": "fill", "ref": "e1", "value": "demo", "reason": "fill account"})
    observation = {
        "url": "http://localhost:5173/#/users",
        "interactives": [{"ref": "e1", "selector": "input.account", "placeholder": "账号"}],
    }

    try:
        asyncio.run(execute_agent_decision(object(), decision, observation))
    except RuntimeError as exc:
        assert "not visible" in str(exc)
    else:
        raise AssertionError("expected not visible failure")

    payload = json.loads(feedback_path.read_text(encoding="utf-8"))
    record = payload["records"][0]
    assert record["success"] is False
    assert record["action"] == "fill"
    assert record["selector"] == "input.account"
    assert "not visible" in record["error"]
    assert payload["stats"][record["key"]]["failed"] == 1


def test_execute_agent_decision_feedback_can_be_disabled(tmp_path, monkeypatch):
    feedback_path = tmp_path / "feedback.json"
    monkeypatch.setenv("ELEMENT_FEEDBACK_PATH", str(feedback_path))
    monkeypatch.setenv("ELEMENT_FEEDBACK_ENABLED", "0")

    class Locator:
        async def click(self, timeout):
            pass

    async def fake_first_visible(page, candidates):
        return Locator()

    monkeypatch.setattr("runner.agent_explore.first_visible", fake_first_visible)
    decision = normalize_decision({"action": "click", "ref": "e1", "reason": "click"})
    observation = {"url": "http://localhost:5173/#/users", "interactives": [{"ref": "e1", "selector": "button.add"}]}

    result = asyncio.run(execute_agent_decision(object(), decision, observation))

    assert result["result"] == "clicked"
    assert not feedback_path.exists()
