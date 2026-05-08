"""core.tool_protocol

职责：
- 宽松解析工具调用 JSON
- 从纯文本中提取 `<tool_use>` / `<tool_call>`
- 从文本中提取 `<thinking>`

边界：
- 这里只负责文本协议和轻量解析
- Session 层复用这里的能力，不再重复实现
"""

import json
import re
from typing import Any, Dict, List, Tuple

from .schema import MockToolCall, MockResponse


def tryparse(json_str: str) -> Dict[str, Any]:
    """
    宽松 JSON 解析：处理 markdown code block、尾部多余字符、半截 JSON。
    """
    try:
        return json.loads(json_str)
    except Exception:
        pass

    for candidate in (
        json_str,
        str(json_str).strip().strip("`").replace("json\n", "", 1).strip(),
    ):
        try:
            return json.loads(candidate)
        except Exception:
            pass

        try:
            return json.loads(candidate[:-1])
        except Exception:
            pass

        if "}" in candidate:
            try:
                return json.loads(candidate[: candidate.rfind("}") + 1])
            except Exception:
                pass

    raise json.JSONDecodeError("unable to parse tool call json", str(json_str), 0)


def parse_text_tool_calls(content: str) -> Tuple[List[MockToolCall], str]:
    """
    从纯文本中提取 <tool_use> / <tool_call>。
    用于不稳定模型或非 native tool calling 的 fallback。
    """
    tool_calls: List[MockToolCall] = []

    json_prefix = next(
        (prefix for prefix in ['[{"type":"tool_use"', '[{"type": "tool_use"'] if prefix in content),
        None,
    )
    if json_prefix and content.endswith("}]"):
        try:
            idx = content.index(json_prefix)
            raw = json.loads(content[idx:])
            tool_calls = [
                MockToolCall(name=b["name"], args=b.get("input", {}), id=b.get("id", ""))
                for b in raw
                if b.get("type") == "tool_use"
            ]
            return tool_calls, content[:idx].strip()
        except Exception:
            pass

    pattern = r"<(?:tool_use|tool_call)>((?:(?!<(?:tool_use|tool_call)>).){15,}?)</(?:tool_use|tool_call)>"

    for raw in re.findall(pattern, content, re.DOTALL):
        try:
            data = tryparse(raw.strip())
            name = data.get("name") or data.get("tool") or data.get("function")
            args = (
                data.get("arguments")
                or data.get("args")
                or data.get("input")
                or data.get("parameters")
                or {}
            )
            if name:
                tool_calls.append(MockToolCall(name=name, args=args))
        except Exception:
            pass

    if tool_calls:
        content = re.sub(pattern, "", content, flags=re.DOTALL).strip()

    return tool_calls, content


def extract_thinking(content: str) -> Tuple[str, str]:
    pattern = r"<think(?:ing)?>(.*?)</think(?:ing)?>"
    match = re.search(pattern, content, re.DOTALL)
    if not match:
        return "", content
    thinking = match.group(1).strip()
    content = re.sub(pattern, "", content, flags=re.DOTALL).strip()
    return thinking, content
