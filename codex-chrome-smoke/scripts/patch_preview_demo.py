"""Patch preview demo — Stage B handshake simulation.

This script simulates what an agent step would *see* once the element
library is hooked into `build_agent_prompt`. It does not modify any
agent code; it just calls the provider with the same arguments the LLM
decide loop would use, so you can preview the rendered candidates next to
the real observation.

Run:
  python scripts/patch_preview_demo.py --intent "退出登录" --route "home"
  python scripts/patch_preview_demo.py --intent "新增设备" --route "#/hubble/device"
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT))

from runner.element_knowledge import format_candidate_elements, rank_for_intent  # noqa: E402

DEFAULT_INTENTS = [
    ("登录", "login"),
    ("退出登录", "home"),
    ("新增设备", "#/hubble/device"),
    ("搜索用户", "#/system/user"),
    ("确认弹窗", "home"),
]


def render(intent: str, route: str) -> None:
    snippet = format_candidate_elements(intent, route)
    if not snippet:
        print(f"\n[{intent!r} @ {route!r}] — no library match; pure agent-loop fallback.")
        return
    print(f"\n[{intent!r} @ {route!r}]")
    print("-" * 60)
    print(snippet)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--intent", default="")
    parser.add_argument("--route", default="")
    parser.add_argument("--json", action="store_true",
                        help="dump raw ranked elements as JSON instead of snippet")
    args = parser.parse_args()

    if args.intent:
        render(args.intent, args.route)
        if args.json:
            print(json.dumps(rank_for_intent(args.intent, args.route), ensure_ascii=False, indent=2))
        return 0

    print("== patch preview — seeing what the agent prompt would gain ==")
    for intent, route in DEFAULT_INTENTS:
        render(intent, route)
    return 0


if __name__ == "__main__":
    sys.exit(main())
