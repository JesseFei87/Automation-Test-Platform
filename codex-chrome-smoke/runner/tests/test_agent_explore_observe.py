import asyncio

from runner.agent_explore import observe_page


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
