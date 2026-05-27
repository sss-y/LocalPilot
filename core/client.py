"""Client wrappers extracted from core.llmcore."""

import json
import os
import re
import sys

from core.mylogging import _write_llm_log as _base_write_llm_log


def _write_llm_log(label, content):
    """Write LLM logs, honoring the legacy core.llmcore hook when patched."""
    llmcore = sys.modules.get("core.llmcore")
    legacy_hook = getattr(llmcore, "_write_llm_log", None) if llmcore else None
    if legacy_hook and legacy_hook is not _legacy_write_llm_log_bridge and legacy_hook is not _base_write_llm_log:
        return legacy_hook(label, content)
    return _base_write_llm_log(label, content)


_legacy_write_llm_log_bridge = _write_llm_log


class MockFunction:
    def __init__(self, name, arguments):
        self.name, self.arguments = name, arguments


class MockToolCall:
    def __init__(self, name, args, id=""):
        arg_str = json.dumps(args, ensure_ascii=False) if isinstance(args, (dict, list)) else (args or "{}")
        self.function = MockFunction(name, arg_str)
        self.id = id


class MockResponse:
    def __init__(self, thinking, content, tool_calls, raw, stop_reason="end_turn"):
        self.thinking = thinking
        self.content = content
        self.tool_calls = tool_calls
        self.raw = raw
        self.stop_reason = "tool_use" if tool_calls else stop_reason

    def __repr__(self):
        return f"<MockResponse thinking={bool(self.thinking)}, content='{self.content}', tools={bool(self.tool_calls)}>"


class ToolClient:
    def __init__(self, backend, auto_save_tokens=True):
        self.backend = backend  # session
        self.auto_save_tokens = auto_save_tokens
        self.last_tools = ""
        self.name = self.backend.name
        self.total_cd_tokens = 0

    def chat(self, messages, tools=None):
        full_prompt = self._build_protocol_prompt(messages, tools)
        print("Full prompt length:", len(full_prompt), "chars")
        gen = self.backend.ask(full_prompt)
        _write_llm_log("Prompt", full_prompt)
        raw_text = ""
        for chunk in gen:
            raw_text += chunk
            yield chunk
        _write_llm_log("Response", raw_text)
        return self._parse_mixed_response(raw_text)

    def _prepare_tool_instruction(self, tools):
        tool_instruction = ""
        if not tools:
            return tool_instruction
        tools_json = json.dumps(tools, ensure_ascii=False, separators=(",", ":"))
        _en = os.environ.get("GA_LANG") == "en"
        if _en:
            tool_instruction = """
### Interaction Protocol (must follow strictly, always in effect)
Follow these steps to think and act:
1. **Think**: Analyze the current situation and strategy inside `<thinking>` tags.
2. **Summarize**: Output a minimal one-line (<30 words) physical snapshot in `<summary>`: new info from last tool result + current tool call intent. This goes into long-term working memory. Must contain real information, no filler.
3. **Act**: If you need to call tools, output one or more **<tool_use> blocks** after your reply, then stop.
"""
        else:
            tool_instruction = """
### 交互协议 (必须严格遵守，持续有效)
请按照以下步骤思考并行动：
1. **思考**: 在 `<thinking>` 标签中先进行思考，分析现状和策略。
2. **总结**: 在 `<summary>` 中输出*极为简短*的高度概括的单行（<30字）物理快照，包括上次工具调用结果产生的新信息+本次工具调用意图。此内容将进入长期工作记忆，记录关键信息，严禁输出无实际信息增量的描述。
3. **行动**: 如需调用工具，请在回复正文之后输出一个（或多个）**<tool_use>块**，然后结束。
"""
        tool_instruction += f'\nFormat: ```<tool_use>{{"name": "tool_name", "arguments": {{...}}}}</tool_use>```\n\n### Tools (mounted, always in effect):\n{tools_json}\n'
        if self.auto_save_tokens and self.last_tools == tools_json:
            tool_instruction = (
                "\n### Tools: still active, **ready to call**. Protocol unchanged.\n"
                if _en
                else "\n### 工具库状态：持续有效（code_run/file_read等），**可正常调用**。调用协议沿用。\n"
            )
        else:
            self.total_cd_tokens = 0
        self.last_tools = tools_json
        return tool_instruction

    def _build_protocol_prompt(self, messages, tools):
        system_content = next((m["content"] for m in messages if m["role"].lower() == "system"), "")
        history_msgs = [m for m in messages if m["role"].lower() != "system"]
        tool_instruction = self._prepare_tool_instruction(tools)
        system = ""
        user = ""
        if system_content:
            system += f"{system_content}\n"
        system += f"{tool_instruction}"
        for m in history_msgs:
            role = "USER" if m["role"] == "user" else "ASSISTANT"
            user += f"=== {role} ===\n"
            for tr in m.get("tool_results", []):
                user += f'<tool_result>{tr["content"]}</tool_result>\n'
            user += str(m["content"]) + "\n"
            self.total_cd_tokens += len(user) // 3
        if self.total_cd_tokens > 9000:
            self.last_tools = ""
        user += "=== ASSISTANT ===\n"
        return system + user

    def _parse_mixed_response(self, text):
        remaining_text = text
        thinking = ""
        think_match = re.search(r"<think(?:ing)?>(.*?)</think(?:ing)?>", text, re.DOTALL)
        if think_match:
            thinking = think_match.group(1).strip()
            remaining_text = re.sub(r"<think(?:ing)?>(.*?)</think(?:ing)?>", "", remaining_text, flags=re.DOTALL)
        tool_calls, remaining_text = _parse_text_tool_calls(remaining_text)
        if not tool_calls:
            json_strs = []
            errors = []
            if "<tool_use>" in remaining_text:
                weaktoolstr = remaining_text.split("<tool_use>")[-1].strip().strip("><")
                json_str = weaktoolstr if weaktoolstr.endswith("}") else ""
                if json_str == "" and "```" in weaktoolstr and weaktoolstr.split("```")[0].strip().endswith("}"):
                    json_str = weaktoolstr.split("```")[0].strip()
                if json_str:
                    json_strs.append(json_str)
                remaining_text = remaining_text.replace("<tool_use>" + weaktoolstr, "")
            elif '"name":' in remaining_text and '"arguments":' in remaining_text:
                json_match = re.search(r'\{.*"name":.*\}', remaining_text, re.DOTALL)
                if json_match:
                    json_strs.append(json_match.group(0).strip())
                    remaining_text = remaining_text.replace(json_match.group(0), "").strip()
            for json_str in json_strs:
                try:
                    data = tryparse(json_str)
                    func_name = data.get("name") or data.get("function") or data.get("tool")
                    args = data.get("arguments") or data.get("args") or data.get("params") or data.get("parameters")
                    if args is None:
                        args = data
                    if func_name:
                        tool_calls.append(MockToolCall(func_name, args))
                except json.JSONDecodeError:
                    errors.append(f"Failed to parse tool_use JSON: {json_str[:200]}")
                    self.last_tools = ""
                except Exception:
                    pass
            if not tool_calls:
                for error in errors:
                    print(f"[Warn] {error}")
                    tool_calls.append(MockToolCall("bad_json", {"msg": error}))
        return MockResponse(thinking, remaining_text.strip(), tool_calls, text)


def _parse_text_tool_calls(content):
    """Fallback: extract tool calls from text when model doesn't use native tool_use blocks."""
    tcs = []
    _jp = next((p for p in ['[{"type":"tool_use"', '[{"type": "tool_use"'] if p in content), None)
    if _jp and content.endswith("}]"):
        try:
            idx = content.index(_jp)
            raw = json.loads(content[idx:])
            tcs = [MockToolCall(b["name"], b.get("input", {}), id=b.get("id", "")) for b in raw if b.get("type") == "tool_use"]
            return tcs, content[:idx].strip()
        except Exception:
            pass
    _xp = r"<(?:tool_use|tool_call)>((?:(?!<(?:tool_use|tool_call)>).){15,}?)</(?:tool_use|tool_call)>"
    for s in re.findall(_xp, content, re.DOTALL):
        try:
            d = tryparse(s.strip())
            name = d.get("name")
            args = d.get("arguments") or d.get("args") or d.get("input") or {}
            if name:
                tcs.append(MockToolCall(name, args))
        except Exception:
            pass
    if tcs:
        content = re.sub(_xp, "", content, flags=re.DOTALL).strip()
    return tcs, content


def tryparse(json_str):
    try:
        return json.loads(json_str)
    except Exception:
        pass
    json_str = json_str.strip().strip("`").replace("json\n", "", 1).strip()
    try:
        return json.loads(json_str)
    except Exception:
        pass
    try:
        return json.loads(json_str[:-1])
    except Exception:
        pass
    if "}" in json_str:
        json_str = json_str[: json_str.rfind("}") + 1]
    return json.loads(json_str)


THINKING_PROMPT_ZH = """
### 行动规范（持续有效）
每次回复（含工具调用轮）都先在回复文字中包含一个<summary></summary> 中输出极简单行（<30字）物理快照：上次结果新信息+本次意图。此内容进入长期工作记忆。
\n**若用户需求未完成，必须进行工具调用！**
""".strip()

THINKING_PROMPT_EN = """
### Action Protocol (always in effect)
The reply body should first include a minimal one-line (<30 words) physical snapshot in <summary></summary>: new info from last result + current intent. This goes into long-term working memory.
\n**If the user's request is not yet complete, tool calls are required!**
""".strip()


class NativeToolClient:
    @staticmethod
    def _thinking_prompt():
        return THINKING_PROMPT_EN if os.environ.get("GA_LANG") == "en" else THINKING_PROMPT_ZH

    def __init__(self, backend):
        self.backend = backend
        self.backend.system = self._thinking_prompt()
        self.name = self.backend.name
        self._pending_tool_ids = []  # 待执行的工具id

    def set_system(self, extra_system):
        combined = f"{extra_system}\n\n{self._thinking_prompt()}" if extra_system else self._thinking_prompt()
        if combined != self.backend.system:
            print(f"[Debug] Updated system prompt, length {len(combined)} chars.")
        self.backend.system = combined

    def chat(self, messages, tools=None):
        if tools:
            self.backend.tools = tools
        combined_content = []
        resp = None
        tool_results = []
        for msg in messages:
            c = msg.get("content", "")
            if msg["role"] == "system":
                self.set_system(c)
                continue
            if isinstance(c, str):
                combined_content.append({"type": "text", "text": c})
            elif isinstance(c, list):
                combined_content.extend(c)
            if msg["role"] == "user" and msg.get("tool_results"):
                tool_results.extend(msg["tool_results"])
        tr_id_set = set()
        tool_result_blocks = []
        for tr in tool_results:
            tool_use_id, content = tr.get("tool_use_id", ""), tr.get("content", "")
            tr_id_set.add(tool_use_id)
            if tool_use_id:
                tool_result_blocks.append({"type": "tool_result", "tool_use_id": tool_use_id, "content": tr.get("content", "")})
            else:
                combined_content = [{"type": "text", "text": f"<tool_result>{content}</tool_result>"}] + combined_content
        for tid in self._pending_tool_ids:
            if tid not in tr_id_set:
                tool_result_blocks.append({"type": "tool_result", "tool_use_id": tid, "content": ""})
        self._pending_tool_ids = []

        merged = {"role": "user", "content": tool_result_blocks + combined_content}
        _write_llm_log("Prompt", json.dumps(merged, ensure_ascii=False, indent=2))
        gen = self.backend.ask(merged)
        try:
            while True:
                chunk = next(gen)
                yield chunk
        except StopIteration as e:
            resp = e.value
        if resp:
            _write_llm_log("Response", resp.raw)
        if resp and hasattr(resp, "tool_calls") and resp.tool_calls:
            self._pending_tool_ids = [tc.id for tc in resp.tool_calls]
        return resp


__all__ = [
    "MockFunction",
    "MockToolCall",
    "MockResponse",
    "ToolClient",
    "NativeToolClient",
    "_parse_text_tool_calls",
    "tryparse",
    "THINKING_PROMPT_ZH",
    "THINKING_PROMPT_EN",
]
