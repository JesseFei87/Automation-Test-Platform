from runner import step_details


def test_planned_steps_prefer_business_steps_over_internal_operations():
    case = {
        "steps": ["1. 登录", "2. 打开退出弹窗", "3. 确认退出"],
        "automation_asset": {"operation_steps": ["fill username", "fill password", "click login", "click logout"]},
    }

    assert step_details.planned_step_titles(case) == case["steps"]


def test_failed_run_maps_only_named_step_screenshots(tmp_path, monkeypatch):
    monkeypatch.setattr(step_details, "STEP_DETAIL_DIR", tmp_path)
    monkeypatch.setattr(step_details, "evidence_summary", lambda _run_id: {})
    case = {"id": "TC-ICM-028", "title": "退出登录", "steps": ["登录", "打开退出弹窗", "确认退出"]}
    result = {
        "status": "failed",
        "error": "confirm failed",
        "screenshots": [
            "screenshots/runs/run-1/01-entry.png",
            "screenshots/runs/run-1/step-01.png",
            "screenshots/runs/run-1/step-02.png",
            "screenshots/runs/run-1/03-final.png",
        ],
    }

    payload = step_details.finalize_step_details("run-1", case, result)

    assert [item["status"] for item in payload["steps"]] == ["completed", "completed", "failed"]
    assert payload["steps"][0]["screenshot_url"].endswith("/step-01.png")
    assert payload["steps"][1]["screenshot_url"].endswith("/step-02.png")
    assert payload["steps"][2]["screenshot_url"].endswith("/03-final.png")


def test_step_screenshot_updates_running_detail_immediately(tmp_path, monkeypatch):
    monkeypatch.setattr(step_details, "STEP_DETAIL_DIR", tmp_path)
    case = {"id": "TC-ICM-028", "title": "退出登录", "steps": ["登录", "打开退出弹窗", "确认退出"]}
    payload = step_details.initialize_step_details("run-live", case)

    assert [item["status"] for item in payload["steps"]] == ["running", "queued", "queued"]

    step_details.record_step_screenshot(
        "run-live",
        "screenshots/runs/run-live/step-01.png",
        "https://example.test/#/icm",
    )
    payload = step_details.load_step_details("run-live")

    assert [item["status"] for item in payload["steps"]] == ["completed", "running", "queued"]
    assert payload["steps"][0]["screenshot_url"] == "/api/screenshots/runs/run-live/step-01.png"


def test_passed_legacy_run_maps_only_final_screenshot_to_last_step(tmp_path, monkeypatch):
    monkeypatch.setattr(step_details, "STEP_DETAIL_DIR", tmp_path)
    monkeypatch.setattr(step_details, "evidence_summary", lambda _run_id: {})
    case = {"id": "TC-ICM-001", "title": "login", "steps": ["open", "fill", "submit"]}
    result = {
        "status": "passed",
        "screenshots": [
            "screenshots/latest/TC-ICM-001/01-entry.png",
            "screenshots/latest/TC-ICM-001/02-action.png",
            "screenshots/latest/TC-ICM-001/03-final.png",
        ],
    }

    payload = step_details.finalize_step_details("run-legacy", case, result)

    assert payload["steps"][0]["screenshot_url"] == ""
    assert payload["steps"][1]["screenshot_url"] == ""
    assert payload["steps"][2]["screenshot_url"] == "/api/screenshots/latest/TC-ICM-001/03-final.png"
