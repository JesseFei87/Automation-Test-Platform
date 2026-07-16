"""回归测试：验证 _evaluate_assertion_check 所有分支输出的中文 reason 不再出现乱码。

运行方式（项目根目录）：
    python scripts/test_assertion_reasons.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# api.py 内部使用 `from icm_platform.ai_service import ...` 这种相对式包导入
sys.path.insert(0, str(ROOT))

from icm_platform import api  # noqa: E402

GARBAGE_MARKERS = ("?", "??")


def _has_garbage(text: str) -> bool:
    """返回 True 表示 reason 里有疑似乱码（连续 2 个以上 ?）。"""
    if not text:
        return False
    return any(marker in text for marker in GARBAGE_MARKERS)


def _run(check: dict, item: dict, trace: dict) -> dict:
    return api._evaluate_assertion_check(check, item, trace)


cases = [
    # url_contains 分支
    {
        "name": "url_contains: 缺 URL（queued）",
        "check": {"type": "url_contains", "expected": "#/usrmgt"},
        "item": {"observation": {}, "decision": {}, "execution": {"result": ""}},
        "trace": {},
        "expect_status": "queued",
        "reason_contains": "URL",
    },
    {
        "name": "url_contains: 命中预期（completed）",
        "check": {"type": "url_contains", "expected": "#/usrmgt"},
        "item": {"observation": {"url": "http://x/#/usrmgt"}, "decision": {}, "execution": {}},
        "trace": {},
        "expect_status": "completed",
        "reason_contains": "URL",
    },
    {
        "name": "url_contains: 账号切换场景（completed）",
        "check": {"type": "url_contains", "expected": "#/login"},
        "item": {"observation": {"url": "http://x/#/index"}, "decision": {}, "execution": {"result": "account_switch_passed"}},
        "trace": {},
        "expect_status": "completed",
        "reason_contains": "账号",
    },
    {
        "name": "url_contains: 未命中（failed）",
        "check": {"type": "url_contains", "expected": "#/usrmgt"},
        "item": {"observation": {"url": "http://x/#/index"}, "decision": {}, "execution": {}},
        "trace": {},
        "expect_status": "failed",
        "reason_contains": "URL",
    },
    # checkbox_checked 分支
    {
        "name": "checkbox_checked: 绑定动作已生效（completed/strict）",
        "check": {"type": "checkbox_checked", "expected": "已选中"},
        "item": {"observation": {}, "decision": {}, "execution": {"result": "user_device_bound"}},
        "trace": {},
        "expect_status": "completed",
        "reason_contains": "复选框",
    },
    {
        "name": "checkbox_checked: 页面观察到勾选（completed/loose）",
        "check": {"type": "checkbox_checked", "expected": "已选中"},
        "item": {"observation": {"visibleText": ["is-checked true 状态"]}, "decision": {}, "execution": {}},
        "trace": {},
        "expect_status": "completed",
        "reason_contains": "复选框",
    },
    {
        "name": "checkbox_checked: 页面未观察到勾选（failed）",
        "check": {"type": "checkbox_checked", "expected": "已选中"},
        "item": {"observation": {"visibleText": ["未勾选状态"]}, "decision": {}, "execution": {}},
        "trace": {},
        "expect_status": "failed",
        "reason_contains": "复选框",
    },
    {
        "name": "checkbox_checked: 缺少证据（queued）",
        "check": {"type": "checkbox_checked", "expected": "已选中"},
        "item": {"observation": {}, "decision": {}, "execution": {}},
        "trace": {},
        "expect_status": "queued",
        "reason_contains": "复选框",
    },
    # login_success 分支
    {
        "name": "login_success: login_guard_passed（completed）",
        "check": {"type": "login_success", "expected": "登录成功"},
        "item": {"observation": {"url": "http://x/#/index"}, "decision": {}, "execution": {"result": "login_guard_passed"}},
        "trace": {},
        "expect_status": "completed",
        "reason_contains": "登录",
    },
    {
        "name": "login_success: URL 已离开登录页（completed）",
        "check": {"type": "login_success", "expected": "登录成功"},
        "item": {"observation": {"url": "http://x/#/index"}, "decision": {}, "execution": {}},
        "trace": {},
        "expect_status": "completed",
        "reason_contains": "URL",
    },
    {
        "name": "login_success: 仍停留在登录页（failed）",
        "check": {"type": "login_success", "expected": "登录成功"},
        "item": {"observation": {"url": "http://x/#/login"}, "decision": {}, "execution": {}},
        "trace": {},
        "expect_status": "failed",
        "reason_contains": "登录",
    },
    {
        "name": "login_success: 缺少证据（queued）",
        "check": {"type": "login_success", "expected": "登录成功"},
        "item": {"observation": {}, "decision": {}, "execution": {}},
        "trace": {},
        "expect_status": "queued",
        "reason_contains": "登录",
    },
]


failures = []
for case in cases:
    result = _run(case["check"], case["item"], case["trace"])
    status = result.get("status")
    reason = result.get("reason") or ""
    ok_status = status == case["expect_status"]
    ok_no_garbage = not _has_garbage(reason)
    ok_contains = case["reason_contains"] in reason
    if not (ok_status and ok_no_garbage and ok_contains):
        failures.append({
            "name": case["name"],
            "got_status": status,
            "got_reason": reason,
            "expect_status": case["expect_status"],
            "ok_status": ok_status,
            "ok_no_garbage": ok_no_garbage,
            "ok_contains": ok_contains,
        })

print(f"用例总数: {len(cases)}")
print(f"失败数:   {len(failures)}")
if failures:
    print("\n失败用例：")
    for f in failures:
        print(f"  - {f['name']}")
        print(f"      期望 status={f['expect_status']}, 实际 status={f['got_status']} (ok={f['ok_status']})")
        print(f"      实际 reason={f['got_reason']!r} (无乱码={f['ok_no_garbage']}, 含关键词={f['ok_contains']})")
    sys.exit(1)
else:
    print("\n全部通过：所有分支的中文 reason 输出正常，无乱码。")