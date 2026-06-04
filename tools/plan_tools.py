"""Plan-mode helpers."""

from __future__ import annotations

import re


def _in_plan_mode(working: dict) -> str | None:
    return working.get("in_plan_mode")


def _exit_plan_mode(working: dict) -> None:
    working.pop("in_plan_mode", None)


def enter_plan_mode(working: dict, plan_path: str) -> str:
    working["in_plan_mode"] = plan_path
    return plan_path


def _check_plan_completion(working: dict) -> int | None:
    plan_path = _in_plan_mode(working)
    if not plan_path:
        return None
    try:
        with open(plan_path, encoding="utf-8", errors="replace") as handle:
            # 统计 [ ] 的数量作为未完成的任务数并返回
            return len(re.findall(r"\[ \]", handle.read()))
    except OSError:
        return None
