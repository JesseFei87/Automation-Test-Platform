from __future__ import annotations

import json
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _diagnose(text: str) -> tuple[str, str, bool]:
    value = text.lower()
    if any(token in value for token in ("selector", "locator", "unknown ref", "target missing", "not visible")):
        return "locator_drift", "定位器或页面结构变化；请结合元素知识库审核替代 selector。", True
    if any(token in value for token in ("login", "password", "unauthorized", "forbidden", "权限")):
        return "auth_expired", "登录会话或权限失效；请核对测试账号和环境权限。", False
    if any(token in value for token in ("timeout", "connection", "network", "environment", "rate_limit", "429", "500", "503")):
        return "environment_error", "环境、网络或服务异常；请先确认测试环境可用性。", False
    if any(token in value for token in ("assert", "expected", "断言")):
        return "business_assertion", "业务断言未满足；请人工确认需求或测试数据是否变化。", False
    return "unknown", "现有证据不足以给出安全的自动修复建议。", False


def _parent_task(parent_run_id: str) -> dict[str, Any]:
    from icm_platform.db import connect

    with connect() as conn:
        row = conn.execute("select case_id, agent_backend from run_tasks where id = ?", (parent_run_id,)).fetchone()
    return dict(row) if row else {}


def _case_arg_for_parent(parent_run_id: str, case_id: str) -> str:
    draft_case = ROOT / "reports" / "draft-runs" / parent_run_id / "case.yaml"
    return str(draft_case) if draft_case.exists() else case_id


def _ai_diagnose(evidence: str, category: str, recommendation: str) -> tuple[str, str, float, str]:
    """Ask the configured platform model only when rule evidence is inconclusive."""
    if category != "unknown":
        return category, recommendation, 0.8, "not_needed"
    try:
        from icm_platform.ai_service import AIService
        from icm_platform.db import get_ai_settings
        from runner.agent_explore import _chat_content, extract_json_object

        settings = get_ai_settings(mask_key=False)
        if not settings.get("api_key") or not settings.get("base_url") or not settings.get("model"):
            return category, recommendation, 0.3, "not_configured"
        prompt = (
            "Classify this browser test failure. Return JSON only: "
            '{"category":"locator_drift|auth_expired|environment_error|business_assertion|unknown",'
            '"recommendation":"short Chinese recommendation","confidence":0-1}. '
            "Do not propose executable code or selectors. Failure evidence:\n" + (evidence[:2000] or "none")
        )
        service = AIService()
        provider = str(settings.get("provider") or "openai")
        payload = {"model": settings["model"], "messages": [{"role": "system", "content": "Return exactly one JSON object."}, {"role": "user", "content": prompt}], "temperature": 0.1, "stream": False, "max_tokens": 300}
        raw = service._post_json(service.chat_completions_url(settings["base_url"]), service.api_key_for_provider(settings), payload, timeout=service.request_timeout(provider))
        answer = extract_json_object(_chat_content(raw))
        proposed = str(answer.get("category") or "unknown")
        if proposed not in {"locator_drift", "auth_expired", "environment_error", "business_assertion", "unknown"}:
            proposed = "unknown"
        confidence = min(0.79, max(0.3, float(answer.get("confidence") or 0.5)))
        return proposed, str(answer.get("recommendation") or recommendation)[:500], confidence, "completed"
    except Exception:
        return category, recommendation, 0.3, "unavailable"


def _selector_suggestion(observation: dict[str, Any], evidence: str) -> dict[str, str] | None:
    words = {word.lower() for word in evidence.replace("\n", " ").split() if len(word) > 2}
    for item in observation.get("interactives") or []:
        selector, text = str(item.get("selector") or ""), str(item.get("text") or item.get("label") or "")
        if selector and any(word in text.lower() for word in words):
            return {"suggested_selector": selector, "observed_text": text[:200]}
    return None


def run_agent_diagnose(parent_run_id: str, run_id: str) -> dict:
    trace = _read_json(ROOT / "reports" / "agent-explore" / parent_run_id / "trace.json")
    step_detail = _read_json(ROOT / "reports" / "step-details" / f"{parent_run_id}.json")
    history_reasons = [
        str((item.get("decision") or {}).get("reason") or item.get("error") or "")
        for item in (trace.get("history") or [])[-3:]
        if isinstance(item, dict)
    ]
    evidence = "\n".join(
        str(value)
        for value in (trace.get("error"), trace.get("summary"), step_detail.get("error"), step_detail.get("summary"), *history_reasons)
        if value
    )
    category, recommendation, has_patch = _diagnose(evidence)
    category, recommendation, confidence, ai_status = _ai_diagnose(evidence, category, recommendation)
    has_patch = category == "locator_drift"
    parent = _parent_task(parent_run_id)
    reobservation: dict[str, Any] | None = None
    if category == "locator_drift" and parent.get("agent_backend") == "harness" and parent.get("case_id"):
        from runner.harness_explore import run_harness_observation

        reobservation = asyncio.run(run_harness_observation(run_id, _case_arg_for_parent(parent_run_id, str(parent["case_id"]))))
    root = ROOT / "reports" / "agent-diagnosis" / run_id
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "pending_review",
        "parent_run_id": parent_run_id,
        "category": category,
        "confidence": confidence,
        "evidence": evidence[:2000] or "未找到可读取的失败轨迹。",
        "recommendation": recommendation,
        "ai_status": ai_status,
        "reobservation": {key: value for key, value in (reobservation or {}).items() if key != "observation"},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (root / "diagnosis.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if has_patch:
        suggestion = _selector_suggestion((reobservation or {}).get("observation") or {}, evidence)
        patch = {"status": "pending_review", "kind": "selector_review", "parent_run_id": parent_run_id, "recommendation": recommendation, "source": "read_only_harness_observation", "suggestion": suggestion}
        (root / "candidate_patch.json").write_text(json.dumps(patch, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
