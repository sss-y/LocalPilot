"""Base protocol objects for tool handlers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


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
        method_name = f"do_{tool_name}"
        if hasattr(self, method_name):
            args["_index"] = index
            yield from try_call_generator(self.tool_before_callback, tool_name, args, response)
            ret = yield from try_call_generator(getattr(self, method_name), args, response)
            yield from try_call_generator(self.tool_after_callback, tool_name, args, response, ret)
            return ret
        if tool_name == "bad_json":
            return StepOutcome(None, next_prompt=args.get("msg", "bad_json"), should_exit=False)
        yield f"未知工具: {tool_name}\n"
        return StepOutcome(None, next_prompt=f"未知工具 {tool_name}", should_exit=False)
