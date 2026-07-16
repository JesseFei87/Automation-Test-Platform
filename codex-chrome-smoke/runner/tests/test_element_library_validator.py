import asyncio

from runner.element_library_validator import validate_element_library


def test_validator_reports_valid_invalid_and_needs_review(tmp_path):
    class Page:
        async def goto(self, *_args, **_kwargs):
            return None

        async def evaluate(self, script, *args):
            if args:
                return {"button.valid": 1, "button.hidden": 1, "button.missing": 0}
            return {
                "url": "https://example.test/#/users",
                "interactives": [{"ref": "e1", "selector": "button.valid"}],
            }

    report = asyncio.run(
        validate_element_library(
            Page(),
            {
                "pages": [{"page_id": "users", "url": "https://example.test/#/users"}],
                "elements": [
                    {"element_id": "users.valid", "page_id": "users", "selectors": ["button.valid"]},
                    {"element_id": "users.review", "page_id": "users", "selectors": ["button.hidden"]},
                    {"element_id": "users.invalid", "page_id": "users", "selectors": ["button.missing"]},
                ],
            },
            output_path=tmp_path / "validation.json",
        )
    )

    assert report["summary"] == {"valid": 1, "invalid": 1, "needs_review": 1}
    assert [record["matched_refs"] for record in report["records"] if record["status"] == "valid"] == [["e1"]]


def test_validator_accepts_current_ref_matched_by_stable_variant(tmp_path):
    class Page:
        async def goto(self, *_args, **_kwargs):
            return None

        async def evaluate(self, _script, *args):
            if args:
                return {"tbody > tr:nth-of-type(1) > button": 0}
            return {
                "url": "https://example.test/#/users",
                "interactives": [{"ref": "e7", "selector": "button:nth-of-type(3)", "testId": "create-user", "tag": "button"}],
            }

    report = asyncio.run(
        validate_element_library(
            Page(),
            {
                "pages": [{"page_id": "users", "url": "https://example.test/#/users"}],
                "elements": [
                    {
                        "element_id": "users.create",
                        "page_id": "users",
                        "selectors": ["tbody > tr:nth-of-type(1) > button"],
                        "locator_variants": [
                            {"kind": "testid", "value": "create-user", "stability": "high"},
                            {"kind": "css", "value": "tbody > tr:nth-of-type(1) > button", "stability": "low"},
                        ],
                    }
                ],
            },
            output_path=tmp_path / "validation.json",
        )
    )

    assert report["summary"] == {"valid": 1, "invalid": 0, "needs_review": 0}
    assert report["records"][0]["matched_refs"] == ["e7"]
