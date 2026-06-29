from pathlib import Path

import yaml

from runner import browser as browser_module


def test_load_case_falls_back_to_source_draft_case_id(tmp_path, monkeypatch):
    case_dir = tmp_path / "test-cases" / "icm"
    case_dir.mkdir(parents=True, exist_ok=True)
    case_path = case_dir / "tc-icm-021-generated.yaml"
    case_path.write_text(
        yaml.safe_dump(
            {
                "id": "TC-ICM-021",
                "title": "填写全部合法字段新增设备信息成功",
                "source_draft_case_id": "ICMDEV_FUN_001",
                "test_data": "连接类型=连接器-1；设备IP=192.168.1.100",
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(browser_module, "ROOT", Path(tmp_path))

    loaded = browser_module.load_case("ICMDEV_FUN_001")

    assert loaded["id"] == "TC-ICM-021"
    assert loaded["source_draft_case_id"] == "ICMDEV_FUN_001"
