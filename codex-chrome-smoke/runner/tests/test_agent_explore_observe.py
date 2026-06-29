import asyncio

from runner.agent_explore import OBSERVE_PAGE_SCRIPT, _target_selector_candidates, observe_page


class FakePage:
    async def evaluate(self, script):
        assert "document.querySelectorAll" in script
        return {
            "url": "http://127.0.0.1/#/login",
            "title": "Login",
            "visibleText": ["Login"],
            "interactives": [
                {"ref": "e1", "tag": "button", "selector": "#go"},
                {"ref": "e2", "tag": "input", "selector": 'input[placeholder="Name"]'},
            ],
        }


def test_observe_page_returns_refs():
    async def scenario():
        return await observe_page(FakePage())

    observation = asyncio.run(scenario())

    refs = [item["ref"] for item in observation["interactives"]]
    assert refs == ["e1", "e2"]
    assert observation["interactives"][0]["selector"] == "#go"


def test_observe_page_script_covers_element_ui_menu_nodes():
    assert ".el-submenu__title" in OBSERVE_PAGE_SCRIPT
    assert ".el-menu-item" in OBSERVE_PAGE_SCRIPT
    assert '[role="menuitem"]' in OBSERVE_PAGE_SCRIPT


def test_target_selector_candidates_fall_back_to_visible_text_for_click():
    target = {"selector": 'a[href="#/hubble/device"]', "text": "设备信息 | ICM"}
    assert _target_selector_candidates(target, "click") == [
        'a[href="#/hubble/device"]',
        "text=设备信息",
        "text=ICM",
    ]
