"""Base protocol objects for tool handlers."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any, Optional

from core.observability import log_event, log_exception, summarize


@dataclass
class StepOutcome:
    data: Any
    next_prompt: Optional[str] = None
    should_exit: bool = False

# 如果函数返回一个生成器对象，则使用yield from来迭代它，直到完成，并返回最终结果；如果函数返回一个普通值，则直接返回该值。
def try_call_generator(func, *args, **kwargs):
    ret = func(*args, **kwargs)
    if hasattr(ret, "__iter__") and not isinstance(ret, (str, bytes, dict, list)):
        ret = yield from ret
    return ret


class BaseHandler:
    def tool_before_callback(self, tool_name, args, response):
        pass

    def tool_after_callback(self, tool_name, args, response, ret):
        pass


    def turn_end_callback(self, response, tool_calls, tool_results, turn, next_prompt, exit_reason):
        return next_prompt

    def dispatch(self, tool_name, args, response, index=0):
        if not isinstance(args, dict):
            log_event(
                "tool_bad_args",
                level="warning",
                component="tools",
                tool_name=tool_name,
                tool_index=index,
                args=summarize(args),
                turn=getattr(self, "current_turn", None),
            )
            return StepOutcome(
                {"status": "error", "msg": "Tool arguments must be a JSON object."},
                next_prompt="\n",
            )
        method_name = f"do_{tool_name}"
        if hasattr(self, method_name):
            args["_index"] = index
            log_event(
                "tool_start",
                component="tools",
                tool_name=tool_name,
                tool_index=index,
                args=summarize({key: value for key, value in args.items() if key != "_index"}),
                turn=getattr(self, "current_turn", None),
            )
            try:
                yield from try_call_generator(self.tool_before_callback, tool_name, args, response)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                log_exception(
                    "tool_callback_exception",
                    exc,
                    level="warning",
                    recoverable=True,
                    component="tools",
                    tool_name=tool_name,
                    callback="before",
                    turn=getattr(self, "current_turn", None),
                )
            start = perf_counter()
            try:
                ret = yield from try_call_generator(getattr(self, method_name), args, response)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                user_msg = f"{type(exc).__name__}: {exc}"
                log_exception(
                    "tool_exception",
                    exc,
                    recoverable=True,
                    user_visible_msg=user_msg,
                    component="tools",
                    tool_name=tool_name,
                    tool_index=index,
                    turn=getattr(self, "current_turn", None),
                )
                yield f"[Status] Tool exception: {user_msg}\n"
                return StepOutcome({"status": "error", "msg": user_msg}, next_prompt="\n")
            duration_ms = round((perf_counter() - start) * 1000, 2)
            try:
                yield from try_call_generator(self.tool_after_callback, tool_name, args, response, ret)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                log_exception(
                    "tool_callback_exception",
                    exc,
                    level="warning",
                    recoverable=True,
                    component="tools",
                    tool_name=tool_name,
                    callback="after",
                    turn=getattr(self, "current_turn", None),
                )
            log_event(
                "tool_end",
                component="tools",
                tool_name=tool_name,
                tool_index=index,
                turn=getattr(self, "current_turn", None),
                duration_ms=duration_ms,
                outcome=summarize(ret),
            )
            return ret
        if tool_name == "bad_json":
            log_event("tool_bad_json", level="warning", component="tools", msg=args.get("msg"))
            return StepOutcome(None, next_prompt=args.get("msg", "bad_json"), should_exit=False)
        log_event("tool_unknown", level="warning", component="tools", tool_name=tool_name, tool_index=index)
        yield f"未知工具: {tool_name}\n"
        return StepOutcome(None, next_prompt=f"未知工具 {tool_name}", should_exit=False)
