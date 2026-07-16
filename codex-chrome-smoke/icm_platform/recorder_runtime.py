from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from icm_platform.db import connect
from icm_platform.recorder import RecorderError, append_action, fail_session
from icm_platform.recorder_locator_recovery import choose_recovered_locator


RECORDER_INIT_SCRIPT = r"""
(() => {
  const text = (node) => (node?.innerText || node?.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 160);
  const role = (node) => node?.getAttribute?.('role') || ({BUTTON: 'button', A: 'link', INPUT: node.type === 'checkbox' ? 'checkbox' : 'textbox', SELECT: 'combobox', TEXTAREA: 'textbox'}[node?.tagName] || '');
  const interactiveTarget = (node) => {
    const element = node instanceof Element ? node : node?.parentElement;
    return element?.closest?.('[data-testid],[data-test],button,a[href],input,select,textarea,[role],[aria-label],[contenteditable=true]') || element || null;
  };
  const captureTarget = (node) => {
    const element = node?.nodeType === Node.ELEMENT_NODE ? node : node?.parentElement;
    return element?.closest?.('[data-testid],[data-test],button,a[href],input,select,textarea,[role],[aria-label],[contenteditable=true]') || element;
  };
  const candidates = (rawNode) => {
    const node = captureTarget(rawNode);
    const label = node?.labels?.[0]?.innerText || node?.getAttribute?.('aria-label') || '';
    const items = [
      ['testid', node?.getAttribute?.('data-testid')],
      ['role', role(node) && (node?.getAttribute?.('aria-label') || text(node) || node?.getAttribute?.('name'))],
      ['label', label],
      ['placeholder', node?.getAttribute?.('placeholder')],
      ['text', text(node)],
      ['css', node?.id ? '#' + CSS.escape(node.id) : ''],
    ].filter(([, value]) => value);
    return items.map(([strategy, value]) => ({ strategy, value, unique: strategy !== 'css' }));
  };
  const recoveryCandidates = (rawNode) => {
    const start = rawNode?.nodeType === Node.ELEMENT_NODE ? rawNode : rawNode?.parentElement;
    const result = [];
    for (let node = start, depth = 0; node && node !== document.body && depth < 4; node = node.parentElement, depth += 1) {
      const classes = Array.from(node.classList || []).filter((name) => /^[a-z][a-z0-9_-]{1,80}$/i.test(name) && !/^el-tooltip-\d+$/i.test(name) && !/^data-v-/i.test(name));
      const value = [node.tagName?.toLowerCase(), ...classes].filter(Boolean).join('.');
      if (value) result.push({ strategy: 'css', value });
    }
    return result;
  };
  const emit = (payload) => window.__qaRecorderEvent?.(payload);
  document.addEventListener('click', (event) => {
    const node = interactiveTarget(event.target);
    const locatorCandidates = candidates(node);
    emit({ type: 'click', locator_candidates: locatorCandidates, recovery_candidates: locatorCandidates.length ? [] : recoveryCandidates(event.target), click_point: { x: event.clientX, y: event.clientY } });
  }, true);
  document.addEventListener('change', (event) => {
    const node = interactiveTarget(event.target);
    const type = node?.type === 'checkbox' ? 'check' : node?.tagName === 'SELECT' ? 'select' : 'fill';
    emit({ type, locator_candidates: candidates(node), value: type === 'check' ? undefined : node?.value, name: node?.name || '', label: node?.getAttribute?.('aria-label') || node?.placeholder || '' });
  }, true);
  document.addEventListener('keydown', (event) => {
    const node = interactiveTarget(event.target);
    if (event.key === 'Enter' || event.key === 'Escape' || event.key === 'Tab') emit({ type: 'press', locator_candidates: candidates(node), value: event.key });
  }, true);
})();
"""


CERTIFICATE_FAILURE_MESSAGE = "录制未启动：入口证书不受信任。请安装企业根 CA 或配置有效证书后重试。"


def classify_runtime_failure(exc: Exception) -> str:
    if "ERR_CERT_AUTHORITY_INVALID" in str(exc):
        return CERTIFICATE_FAILURE_MESSAGE
    return f"录制浏览器启动失败：{exc}"


@dataclass
class RecorderRuntimeState:
    session_id: str
    stop_requested: threading.Event = field(default_factory=threading.Event)
    finished: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None
    current_url: str | None = None
    error: str | None = None


class RecorderRuntime:
    """Owns short-lived isolated browser processes for recorder sessions."""

    def __init__(self) -> None:
        self._states: dict[str, RecorderRuntimeState] = {}
        self._lock = threading.Lock()

    def start(self, session_id: str, start_url: str) -> RecorderRuntimeState:
        with self._lock:
            if session_id in self._states:
                raise RecorderError("recording browser is already active")
            state = RecorderRuntimeState(session_id=session_id, current_url=start_url)
            state.thread = threading.Thread(target=self._thread_main, args=(state, start_url), daemon=True, name=f"recorder-{session_id}")
            self._states[session_id] = state
            state.thread.start()
            return state

    def get(self, session_id: str) -> RecorderRuntimeState | None:
        with self._lock:
            return self._states.get(session_id)

    def stop(self, session_id: str, timeout: float = 8.0) -> RecorderRuntimeState | None:
        state = self.get(session_id)
        if not state:
            return None
        state.stop_requested.set()
        if state.thread:
            state.thread.join(timeout=timeout)
        return state

    def _thread_main(self, state: RecorderRuntimeState, start_url: str) -> None:
        try:
            asyncio.run(self._record(state, start_url))
        except Exception as exc:
            state.error = classify_runtime_failure(exc)
            with connect() as conn:
                fail_session(conn, state.session_id, state.error)
        finally:
            state.finished.set()

    async def _record(self, state: RecorderRuntimeState, start_url: str) -> None:
        async with async_playwright() as playwright:
            browser: Browser = await playwright.chromium.launch(headless=False)
            context: BrowserContext = await browser.new_context(ignore_https_errors=False)
            page: Page = await context.new_page()

            async def validate_recovery_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
                point = payload.get("click_point") if isinstance(payload.get("click_point"), dict) else {}
                x, y = point.get("x"), point.get("y")
                validated: list[dict[str, Any]] = []
                for raw in payload.get("recovery_candidates") or []:
                    if not isinstance(raw, dict) or raw.get("strategy") not in {"css", "xpath"}:
                        continue
                    selector = str(raw.get("value") or "").strip()
                    if not selector:
                        continue
                    try:
                        locator = page.locator(selector) if raw["strategy"] == "css" else page.locator(f"xpath={selector}")
                        unique = await locator.count() == 1
                        if not unique:
                            validated.append({**raw, "unique": False})
                            continue
                        visible, enabled = await locator.is_visible(), await locator.is_enabled()
                        box = await locator.bounding_box()
                        covers_click_point = bool(box and isinstance(x, (int, float)) and isinstance(y, (int, float)) and box["x"] <= x <= box["x"] + box["width"] and box["y"] <= y <= box["y"] + box["height"])
                        trial_clickable = False
                        if visible and enabled and covers_click_point:
                            await locator.click(trial=True, timeout=750)
                            trial_clickable = True
                        validated.append({**raw, "unique": True, "visible": visible, "enabled": enabled, "covers_click_point": covers_click_point, "trial_clickable": trial_clickable})
                    except Exception:
                        validated.append({**raw, "unique": False})
                return validated

            async def receive_event(_source: Any, payload: Any) -> None:
                if not isinstance(payload, dict):
                    return
                try:
                    if not payload.get("locator_candidates") and payload.get("recovery_candidates"):
                        decision = choose_recovered_locator(await validate_recovery_candidates(payload))
                        if decision.candidate:
                            payload["locator_candidates"] = [decision.candidate.as_recorder_candidate()]
                    with connect() as conn:
                        append_action(conn, state.session_id, payload)
                except RecorderError:
                    return

            async def capture_navigation(frame: Any) -> None:
                if frame != page.main_frame or not frame.url or frame.url == start_url:
                    return
                state.current_url = frame.url
                try:
                    with connect() as conn:
                        append_action(conn, state.session_id, {"type": "navigate", "url": frame.url})
                except RecorderError:
                    state.error = "navigation left the allowlisted recording origin"
                    state.stop_requested.set()

            async def capture_popup(popup: Page) -> None:
                state.current_url = popup.url or state.current_url
                try:
                    with connect() as conn:
                        append_action(conn, state.session_id, {"type": "popup", "url": popup.url or start_url})
                except RecorderError:
                    state.error = "popup left the allowlisted recording origin"
                    state.stop_requested.set()

            await page.expose_binding("__qaRecorderEvent", receive_event)
            await page.add_init_script(RECORDER_INIT_SCRIPT)
            page.on("framenavigated", lambda frame: asyncio.create_task(capture_navigation(frame)))
            context.on("page", lambda popup: asyncio.create_task(capture_popup(popup)))
            await page.goto(start_url, wait_until="domcontentloaded")
            state.current_url = page.url
            await asyncio.to_thread(state.stop_requested.wait)
            await context.close()
            await browser.close()
