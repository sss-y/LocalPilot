"""core.schema

职责：
- 定义跨 provider 统一使用的响应数据结构
- 让上层只面对 MockResponse / MockToolCall，而不用关心底层厂商差异

边界：
- 这里只放数据结构，不放请求逻辑和解析逻辑
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import json


@dataclass
class MockFunction:
    name: str
    arguments: str


@dataclass
class MockToolCall:
    name: str
    args: Any
    id: str = ""

    @property
    def function(self) -> MockFunction:
        if isinstance(self.args, (dict, list)):
            arguments = json.dumps(self.args, ensure_ascii=False)
        else:
            arguments = self.args or "{}"
        return MockFunction(
            name=self.name,
            arguments=arguments
        )


# 和之前的区别:添加了新的usage字段,并且对stop_reason字段的赋值,修改成:如果tool_calls非空则stop_reason为tool_use,否则为end_turn。
@dataclass
class MockResponse:
    thinking: str = ""
    content: str = ""
    tool_calls: List[MockToolCall] = field(default_factory=list)
    raw: Any = None
    stop_reason: str = "end_turn"
    usage: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.tool_calls:
            self.stop_reason = "tool_use"
