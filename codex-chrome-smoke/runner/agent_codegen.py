from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from runner.agent_stage_router import parse_case_test_data, saved_device_name_value


def _quote(value: object) -> str:
    return repr(str(value or ""))


def _goto(decision: dict, execution: dict) -> str | None:
    url = decision.get("url")
    return f"    await page.goto({_quote(url)}, wait_until='domcontentloaded')" if url else None


def _fill(decision: dict, execution: dict) -> str | None:
    selector = execution.get("selector")
    return (
        f"    await fill_first(page, [{_quote(selector)}], {_quote(decision.get('value'))})"
        if selector
        else None
    )


def _click(decision: dict, execution: dict) -> str | None:
    selector = execution.get("selector")
    return f"    await click_first(page, [{_quote(selector)}])" if selector else None


def _press(decision: dict, execution: dict) -> str | None:
    selector = execution.get("selector")
    key = decision.get("key") or execution.get("key") or "Enter"
    return f"    await page.locator({_quote(selector)}).first.press({_quote(key)})" if selector else None


def _wait(decision: dict, execution: dict) -> str | None:
    return "    await page.wait_for_timeout(1200)"


def _scroll(decision: dict, execution: dict) -> str | None:
    value = str(decision.get("value") or 650)
    return f"    await page.mouse.wheel(0, {int(value) if value.isdigit() else 650})"


def _assert_text(decision: dict, execution: dict) -> str | None:
    value = decision.get("value")
    return f"    await ensure_text_visible(page, {_quote(value)})" if value else None


_EMITTERS: dict[str, Callable[[dict, dict], str | None]] = {
    "goto": _goto,
    "fill": _fill,
    "click": _click,
    "press": _press,
    "wait": _wait,
    "scroll": _scroll,
    "assert_text": _assert_text,
}

_LOGIN_STEP_RE = re.compile(r"使用\s*([^\s/]+)/([^\s]+)\s*登录")
_LOGIN_PRECONDITION_RE = re.compile(r"已使用\s*([^\s/]+)/([^\s]+)\s*登录")


def _is_icm_device_create_case(case: dict[str, Any] | None) -> bool:
    if not case:
        return False
    haystack = " ".join(
        [
            str(case.get("id") or ""),
            str(case.get("module") or ""),
            str(case.get("title") or ""),
            " ".join(str(item) for item in case.get("steps") or []),
        ]
    )
    return "设备信息" in haystack and any(token in haystack for token in ("新增", "添加"))


def _extract_login_credentials(case: dict[str, Any] | None, trace: dict[str, Any]) -> tuple[str, str]:
    text_parts = [
        str((case or {}).get("precondition") or ""),
        " ".join(str(item) for item in (case or {}).get("steps") or []),
        str(trace.get("goal") or ""),
    ]
    haystack = "\n".join(text_parts)
    match = _LOGIN_STEP_RE.search(haystack) or _LOGIN_PRECONDITION_RE.search(haystack)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return "admin", "Hubble_Service!1088"


def _generate_icm_device_create_flow(trace: dict[str, Any], case: dict[str, Any]) -> str:
    data = parse_case_test_data(case)
    username, password = _extract_login_credentials(case, trace)
    connection_type = data.get("连接类型") or "连接器-1"
    device_type = data.get("设备类型") or "标准设备"
    device_name = data.get("设备名称") or "TestDev_01"
    saved_device_name = saved_device_name_value(data) or device_name
    device_ip = data.get("设备IP") or "192.168.1.100"
    device_port = data.get("设备端口") or "22"
    device_mac = data.get("设备MAC") or ""
    network_mask = data.get("网络掩码") or ""
    vnc_username = data.get("VNC账号") or ""
    vnc_password = data.get("VNC密码") or ""
    allow_control = data.get("是否允许控制") or "是"
    device_status = data.get("设备状态") or "在线"
    remark = data.get("备注") or ""

    lines = [
        "from __future__ import annotations",
        "",
        "from runner.browser import ensure_text_visible, goto_route",
        "from runner.flows.icm_common import (",
        "    click_dialog_primary,",
        "    ensure_fresh_login,",
        "    ensure_switch_enabled,",
        "    search_by_keyword,",
        "    settle,",
        "    wait_for_visible_dialog,",
        ")",
        "",
        "",
        "async def _choose_dropdown(page, field, value: str) -> None:",
        "    await field.click(force=True)",
        "    await page.wait_for_timeout(300)",
        "    dropdown = page.locator('.el-select-dropdown:visible').last",
        "    option = dropdown.locator('.el-select-dropdown__item').filter(has_text=value).first",
        "    await option.wait_for(state='visible', timeout=5000)",
        "    await option.click(force=True)",
        "",
        "",
        "async def run(page, system, case) -> None:",
        "    # Generated from successful Agent exploration. Review before registration.",
        f"    await ensure_fresh_login(page, system, username={_quote(username)}, password={_quote(password)})",
        "    await goto_route(page, system, '#/hubble/device')",
        "    await settle(page, 1200)",
        "    await search_by_keyword(",
        "        page,",
        "        [",
        "            'css=input[placeholder=\"请输入设备名称\"]',",
        "            'css=input[placeholder=\"输入设备名称\"]',",
        "        ],",
        f"        {_quote(saved_device_name)},",
        "    )",
        f"    if await page.locator('tbody tr').filter(has_text={_quote(saved_device_name)}).count():",
        f"        await ensure_text_visible(page, {_quote(saved_device_name)})",
        "        return",
        "",
        "    await page.get_by_role('button', name='新增').first.click(force=True)",
        "    dialog = await wait_for_visible_dialog(page)",
        "    inputs = dialog.locator('input')",
        f"    await _choose_dropdown(page, inputs.nth(0), {_quote(connection_type)})",
        f"    await _choose_dropdown(page, inputs.nth(1), {_quote(device_type)})",
        f"    await inputs.nth(2).fill({_quote(device_name)})",
        f"    await inputs.nth(3).fill({_quote(device_ip)})",
        f"    await inputs.nth(4).fill({_quote(device_port)})",
    ]

    if device_mac:
        lines.append(f"    await inputs.nth(5).fill({_quote(device_mac)})")
    if network_mask:
        lines.append(f"    await inputs.nth(6).fill({_quote(network_mask)})")
    if vnc_username:
        lines.append(f"    await inputs.nth(7).fill({_quote(vnc_username)})")
    if vnc_password:
        lines.append(f"    await inputs.nth(8).fill({_quote(vnc_password)})")

    lines.extend(
        [
            f"    await _choose_dropdown(page, inputs.nth(9), {_quote(allow_control)})",
        ]
    )
    if device_status in {"在线", "启用", "开启", "是", "true", "True"}:
        lines.append("    await ensure_switch_enabled(page, dialog.locator('.el-switch').last)")
    if remark:
        lines.extend(
            [
                "    remark_field = dialog.locator(\"textarea:visible, input[placeholder*='备注']:visible, textarea[placeholder*='备注']:visible\").first",
                "    if await remark_field.count():",
                f"        await remark_field.fill({_quote(remark)})",
            ]
        )
    lines.extend(
        [
            "    await click_dialog_primary(page)",
            "    dialog_after_submit = page.locator('.el-dialog:visible, .el-drawer:visible')",
            "    if await dialog_after_submit.count():",
            "        await dialog_after_submit.first.wait_for(state='hidden', timeout=5000)",
            "    await settle(page, 1200)",
            "    await search_by_keyword(",
            "        page,",
            "        [",
            "            'css=input[placeholder=\"请输入设备名称\"]',",
            "            'css=input[placeholder=\"输入设备名称\"]',",
            "        ],",
            f"        {_quote(saved_device_name)},",
            "        settle_ms=1200,",
            "    )",
            f"    await ensure_text_visible(page, {_quote(saved_device_name)})",
            f"    await ensure_text_visible(page, {_quote(device_ip)})",
        ]
    )
    if device_status:
        lines.append(f"    await ensure_text_visible(page, {_quote('在线' if device_status in {'在线', '启用', '开启', '是'} else device_status)})")
    return "\n".join(lines) + "\n"


def generate_candidate_flow(trace: dict, case: dict[str, Any] | None = None) -> str:
    if _is_icm_device_create_case(case):
        return _generate_icm_device_create_flow(trace, case or {})

    lines = [
        "from __future__ import annotations",
        "",
        "from runner.browser import click_first, ensure_text_visible, fill_first, goto_route",
        "",
        "",
        "async def run(page, system, case) -> None:",
        "    # Generated from successful Agent exploration. Review before registration.",
    ]
    generated = [
        line
        for item in trace.get("history") or []
        for decision in [item.get("decision") or {}]
        for emitter in [_EMITTERS.get(decision.get("action"))]
        for line in [emitter(decision, item.get("execution") or {}) if emitter else None]
        if line
    ]
    lines.extend(generated or ["    raise RuntimeError('Agent trace did not contain executable actions')"])
    return "\n".join(lines) + "\n"
