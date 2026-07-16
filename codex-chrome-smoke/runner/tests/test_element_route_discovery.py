from __future__ import annotations

import asyncio

from runner import element_route_discovery as discovery
from runner.agent_actions import AgentDecision


def test_discover_routes_walks_observed_navigation_queue(monkeypatch):
    class Page:
        url = "https://example.test/#/index"

        async def goto(self, url, **_kwargs):
            self.url = url

    page = Page()
    observations = {
        "https://example.test/#/index": {
            "url": "https://example.test/#/index",
            "navigationLinks": [{"href": "#/users", "text": "Users"}],
            "interactives": [],
        },
        "https://example.test/#/users": {
            "url": "https://example.test/#/users",
            "navigationLinks": [{"href": "#/servers", "text": "Servers"}],
            "interactives": [],
        },
        "https://example.test/#/servers": {
            "url": "https://example.test/#/servers",
            "navigationLinks": [{"href": "#/users", "text": "Users"}],
            "interactives": [],
        },
    }
    events = []

    async def fake_observe(current_page):
        return observations[current_page.url]

    async def fake_loop(*_args, **_kwargs):
        return {"ok": True, "status": "passed", "history": [{"step": 1, "decision": {"action": "finish", "reason": "navigation exposed"}}]}

    monkeypatch.setattr(discovery, "observe_page", fake_observe)
    monkeypatch.setattr(discovery, "run_agent_loop", fake_loop)

    routes = asyncio.run(
        discovery.discover_routes(
            page,
            base_url="https://example.test",
            max_actions=6,
            max_pages=10,
            progress_callback=events.append,
        )
    )

    assert [item["page_id"] for item in routes] == ["index", "users", "servers"]
    assert [event["stage"] for event in events].count("route_queue_enqueued") == 2
    assert any(
        event["stage"] == "route_candidate_observed"
        and event["href"] == "#/users"
        and event["decision"] == "eligible"
        for event in events
    )
    assert events[-1] == {
        "stage": "route_discovery_completed",
        "discovered_page_count": 3,
        "visited_route_count": 3,
        "route_action_count": 0,
        "agent_failure_count": 0,
        "agent_budget_exhaustion_count": 0,
        "queued_route_count": 0,
    }


def test_discover_routes_logs_agent_failures_without_hiding_them(monkeypatch):
    class Page:
        url = "https://example.test/#/index"

    events = []

    async def fake_observe(_page):
        return {"url": "https://example.test/#/index", "navigationLinks": [], "interactives": []}

    async def fake_loop(*_args, **_kwargs):
        return {
            "ok": False,
            "status": "failed",
            "error": "unknown ref: e404",
            "history": [{"step": 1, "decision": {"action": "click", "ref": "e404", "reason": "bad navigation"}, "execution": {"result": "error", "error": "unknown ref: e404"}}],
        }

    monkeypatch.setattr(discovery, "observe_page", fake_observe)
    monkeypatch.setattr(discovery, "run_agent_loop", fake_loop)

    routes = asyncio.run(discovery.discover_routes(Page(), base_url="https://example.test", progress_callback=events.append))

    assert [item["page_id"] for item in routes] == ["index"]
    assert any(event["stage"] == "route_agent_decision" and event["ref"] == "e404" for event in events)
    assert any(event["stage"] == "route_agent_failed" and event["error"] == "unknown ref: e404" for event in events)
    assert events[-1]["agent_failure_count"] == 1


def test_navigation_candidates_support_menu_data_index():
    candidates = discovery._navigation_candidates(
        {
            "url": "https://example.test/#/index",
            "navigationLinks": [
                {"href": "#/users", "text": "Users"},
                {"href": "/#/servers", "text": "Servers"},
                {"href": "3", "text": "Non-route menu index"},
            ],
        },
        "https://example.test",
    )

    assert [candidate["page_id"] for candidate in candidates] == ["users", "servers"]


def test_discover_routes_enqueues_links_revealed_after_a_safe_action(monkeypatch):
    class Page:
        url = "https://example.test/#/index"
        expanded = False

        async def goto(self, url, **_kwargs):
            self.url = url

    page = Page()
    events = []

    async def fake_observe(current_page):
        if current_page.url.endswith("#/users"):
            return {"url": current_page.url, "navigationLinks": [], "interactives": []}
        return {
            "url": current_page.url,
            "navigationLinks": [{"href": "#/users", "text": "Users"}] if current_page.expanded else [],
            "interactives": [{"ref": "e1", "tag": "li", "role": "menuitem", "text": "System", "selector": ".el-menu-item"}],
        }

    async def fake_execute(_page, _decision, _observation):
        page.expanded = True
        return {"result": "hovered"}

    async def fake_loop(_goal, observe, _decide, execute, *_args, **_kwargs):
        observation = await observe()
        if observation["interactives"]:
            execution = await execute(AgentDecision(action="hover", ref="e1", reason="expand menu"), observation)
            return {"ok": True, "status": "passed", "history": [{"step": 1, "decision": {"action": "hover", "ref": "e1"}, "execution": execution}]}
        return {"ok": True, "status": "passed", "history": []}

    monkeypatch.setattr(discovery, "observe_page", fake_observe)
    monkeypatch.setattr(discovery, "execute_agent_decision", fake_execute)
    monkeypatch.setattr(discovery, "run_agent_loop", fake_loop)

    routes = asyncio.run(discovery.discover_routes(page, base_url="https://example.test", progress_callback=events.append))

    assert [route["page_id"] for route in routes] == ["index", "users"]
    assert any(event["stage"] == "route_queue_enqueued" and event["page_id"] == "users" for event in events)


def test_discover_routes_reports_budget_exhaustion_separately(monkeypatch):
    class Page:
        url = "https://example.test/#/index"

    events = []

    async def fake_observe(_page):
        return {"url": "https://example.test/#/index", "navigationLinks": [], "interactives": []}

    async def fake_loop(*_args, **_kwargs):
        return {"ok": False, "status": "failed", "error": "Agent reached max steps (3).", "history": []}

    monkeypatch.setattr(discovery, "observe_page", fake_observe)
    monkeypatch.setattr(discovery, "run_agent_loop", fake_loop)

    asyncio.run(discovery.discover_routes(Page(), base_url="https://example.test", progress_callback=events.append))

    assert any(event["stage"] == "route_agent_budget_exhausted" for event in events)
    assert not any(event["stage"] == "route_agent_failed" for event in events)
    assert events[-1]["agent_failure_count"] == 0
    assert events[-1]["agent_budget_exhaustion_count"] == 1


def test_discover_routes_logs_rejected_and_skipped_visible_candidates(monkeypatch):
    class Page:
        url = "https://example.test/#/index"

        async def goto(self, url, **_kwargs):
            self.url = url

    page = Page()
    events = []

    async def fake_observe(current_page):
        return {
            "url": current_page.url,
            "navigationLinks": [
                {"href": "#/users", "text": "Users"},
                {"href": "3", "text": "Non-route menu index"},
            ],
            "interactives": [],
        }

    async def fake_loop(*_args, **_kwargs):
        return {"ok": True, "status": "passed", "history": []}

    monkeypatch.setattr(discovery, "observe_page", fake_observe)
    monkeypatch.setattr(discovery, "run_agent_loop", fake_loop)

    asyncio.run(discovery.discover_routes(page, base_url="https://example.test", progress_callback=events.append))

    assert any(event["stage"] == "route_candidate_observed" and event["decision"] == "rejected" and event["reason"] == "unsupported_route_value" for event in events)
    assert any(event["stage"] == "route_queue_skipped" and event["reason"] == "already_visited" for event in events)


def test_safe_navigation_target_rejects_destructive_action():
    observation = {"interactives": [{"ref": "e1", "tag": "a", "role": "link", "text": "Delete user", "selector": "a.delete"}]}

    assert discovery._safe_navigation_target(observation, "e1") is False
