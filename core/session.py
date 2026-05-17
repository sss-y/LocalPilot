"""core.session

职责：
- 承接模型会话主干
- 把内部消息结构转换成 LiteLLM 可调用格式
- 统一解析 text / thinking / tool_use
- 提供普通会话、native 会话和 fallback / router 会话
- 对接 `core.context`、`core.tool_protocol`、`core.logging`

边界：
- 配置读取交给 `core.config`
- 上下文裁剪交给 `core.context`
- 文本工具协议交给 `core.tool_protocol`
- 统一数据结构交给 `core.schema`
"""

import json
import os
import re
import threading
import time
import logging
from copy import copy

from core.context import (
    _drop_unsigned_thinking,
    _ensure_thinking_blocks,
    fix_messages as _fix_messages,
    trim_messages_history,
)
from core.mylogging import LLMLogger
from core.schema import MockResponse, MockToolCall
from core.tool_protocol import (
    extract_thinking,
    parse_text_tool_calls as _parse_text_tool_calls,
    tryparse,
)


def _msgs_claude2oai(messages):
    result = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        blocks = content if isinstance(content, list) else [{"type": "text", "text": str(content)}]
        if role == "assistant":
            text_parts, tool_calls, reasoning = [], [], ""
            for b in blocks:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "thinking" and b.get("thinking"):
                    reasoning = b["thinking"]
                elif b.get("type") == "text" and b.get("text"):
                    text_parts.append({"type": "text", "text": b.get("text", "")})
                elif b.get("type") == "tool_use":
                    tool_calls.append(
                        {
                            "id": b.get("id") or "",
                            "type": "function",
                            "function": {
                                "name": b.get("name", ""),
                                "arguments": json.dumps(b.get("input", {}), ensure_ascii=False),
                            },
                        }
                    )
            m = {"role": "assistant"}
            if reasoning:
                m["reasoning_content"] = reasoning
            m["content"] = text_parts if text_parts else ""
            if tool_calls:
                m["tool_calls"] = tool_calls
            if not text_parts and not tool_calls and reasoning:
                m["content"] = "."
            result.append(m)
        elif role == "user":
            text_parts = []
            for b in blocks:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_result":
                    if text_parts:
                        result.append({"role": "user", "content": text_parts})
                        text_parts = []
                    tr = b.get("content", "")
                    if isinstance(tr, list):
                        tr = "\n".join(
                            x.get("text", "")
                            for x in tr
                            if isinstance(x, dict) and x.get("type") == "text"
                        )
                    result.append(
                        {
                            "role": "tool",
                            "tool_call_id": b.get("tool_use_id") or "",
                            "content": tr if isinstance(tr, str) else str(tr),
                        }
                    )
                elif b.get("type") == "image":
                    src = b.get("source") or {}
                    if src.get("type") == "base64" and src.get("data"):
                        text_parts.append(
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{src.get('media_type', 'image/png')};base64,{src.get('data', '')}"
                                },
                            }
                        )
                elif b.get("type") == "image_url":
                    text_parts.append(b)
                elif b.get("type") == "text" and b.get("text"):
                    text_parts.append({"type": "text", "text": b.get("text", "")})
            if text_parts:
                result.append({"role": "user", "content": text_parts})
        else:
            result.append(msg)
    return result

def openai_tools_to_claude(tools):
    result = []
    for tool in tools:
        if "input_schema" in tool:
            result.append(tool)
            continue
        fn = tool.get("function", tool)
        result.append(
            {
                "name": fn["name"],
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
            }
        )
    return result


def _infer_litellm_provider(sess):
    explicit = getattr(sess, "provider", None) or getattr(sess, "custom_llm_provider", None)
    if explicit:
        return explicit

    model = (getattr(sess, "model", "") or "").lower()
    api_base = (getattr(sess, "api_base", "") or "").lower()
    name = (getattr(sess, "name", "") or "").lower()

    if "/" in model:
        return model.split("/", 1)[0]
    if "anthropic" in api_base or "claude" in model or "claude" in name:
        return "anthropic"
    if "openai" in api_base:
        return "openai"
    if "dashscope" in api_base or "aliyuncs.com" in api_base:
        if "anthropic" in api_base:
            return "anthropic"
        return "openai"
    if "deepseek" in model:
        return "openai"
    return "openai"


def _litellm_model_name(sess):
    model = getattr(sess, "model", "")
    if "/" in model:
        return model
    return f"{_infer_litellm_provider(sess)}/{model}"


def _text_from_delta_content(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") in {"text", "output_text"} and item.get("text"):
                    texts.append(item["text"])
            elif getattr(item, "text", None):
                texts.append(item.text)
        return "".join(texts)
    return ""


def _extract_reasoning_from_obj(obj):
    if obj is None:
        return ""
    for attr in ("reasoning_content", "reasoning", "thinking"):
        value = getattr(obj, attr, None)
        if isinstance(value, str) and value:
            return value
    if isinstance(obj, dict):
        for key in ("reasoning_content", "reasoning", "thinking"):
            value = obj.get(key)
            if isinstance(value, str) and value:
                return value
    return ""


def _message_text_content(message):
    if message is None:
        return ""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") in {"text", "output_text"} and item.get("text"):
                    texts.append(item["text"])
            elif getattr(item, "text", None):
                texts.append(item.text)
        return "".join(texts)
    return str(content or "")


def _merge_stream_tool_call(acc, delta_tc):
    idx = getattr(delta_tc, "index", None)
    if idx is None and isinstance(delta_tc, dict):
        idx = delta_tc.get("index", 0)
    idx = 0 if idx is None else idx
    tool = acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})

    tool_id = getattr(delta_tc, "id", None)
    if tool_id is None and isinstance(delta_tc, dict):
        tool_id = delta_tc.get("id")
    if tool_id:
        tool["id"] = tool_id

    function = getattr(delta_tc, "function", None)
    if function is None and isinstance(delta_tc, dict):
        function = delta_tc.get("function", {})

    fn_name = getattr(function, "name", None)
    if fn_name is None and isinstance(function, dict):
        fn_name = function.get("name")
    if fn_name:
        tool["name"] = fn_name

    fn_args = getattr(function, "arguments", None)
    if fn_args is None and isinstance(function, dict):
        fn_args = function.get("arguments")
    if fn_args:
        tool["arguments"] += fn_args


def _tool_blocks_from_map(tool_map):
    blocks = []
    for tool in tool_map.values():
        if not tool["name"]:
            continue
        try:
            parsed_args = json.loads(tool["arguments"] or "{}")
        except json.JSONDecodeError:
            parsed_args = {"raw_arguments": tool["arguments"]}
        blocks.append(
            {
                "type": "tool_use",
                "id": tool["id"],
                "name": tool["name"],
                "input": parsed_args,
            }
        )
    return blocks


def _tool_blocks_from_message(message):
    tool_calls = getattr(message, "tool_calls", None) or []
    tool_map = {}
    for idx, tool_call in enumerate(tool_calls):
        tool_map[idx] = {
            "id": getattr(tool_call, "id", "") or "",
            "name": getattr(getattr(tool_call, "function", None), "name", "") or "",
            "arguments": getattr(getattr(tool_call, "function", None), "arguments", "") or "",
        }
    return _tool_blocks_from_map(tool_map)


def _build_content_blocks(text, reasoning, tool_blocks):
    blocks = []
    if reasoning:
        blocks.append({"type": "thinking", "thinking": reasoning})
    if text:
        blocks.append({"type": "text", "text": text})
    blocks.extend(tool_blocks)
    return blocks


def _text_from_content_item(item):
    if item is None:
        return ""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        for key in ("text", "output_text", "input_text", "content", "output", "value"):
            value = item.get(key)
            if isinstance(value, str) and value:
                return value
    for attr in ("text", "output_text", "input_text", "content", "output", "value"):
        value = getattr(item, attr, None)
        if isinstance(value, str) and value:
            return value
    return ""


def _collect_text_from_content(content):
    if isinstance(content, str):
        return content
    texts = []
    for item in content or []:
        text = _text_from_content_item(item)
        if text:
            texts.append(text)
    return "".join(texts)


def _stringify_tool_result_content(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        )
    return json.dumps(content, ensure_ascii=False) if isinstance(content, (dict, list)) else str(content or "")


def _parse_jsonish_arguments(arguments):
    if isinstance(arguments, dict):
        return arguments
    if not arguments:
        return {}
    try:
        return json.loads(arguments)
    except (TypeError, json.JSONDecodeError):
        return {"raw_arguments": arguments}


def _response_usage_dict(usage):
    if usage is None:
        return {}
    if isinstance(usage, dict):
        return usage
    if hasattr(usage, "model_dump"):
        try:
            return usage.model_dump()
        except TypeError:
            pass
    if hasattr(usage, "dict"):
        try:
            return usage.dict()
        except TypeError:
            pass
    if hasattr(usage, "__dict__"):
        return {k: v for k, v in vars(usage).items() if not k.startswith("_")}
    return {"value": usage}


def _response_to_raw_string(response):
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        return json.dumps(response, ensure_ascii=False, default=str)
    if hasattr(response, "model_dump_json"):
        try:
            return response.model_dump_json()
        except TypeError:
            pass
    if hasattr(response, "model_dump"):
        try:
            return json.dumps(response.model_dump(), ensure_ascii=False, default=str)
        except TypeError:
            pass
    if hasattr(response, "dict"):
        try:
            return json.dumps(response.dict(), ensure_ascii=False, default=str)
        except TypeError:
            pass
    return str(response)


def _content_item_to_input_item(item):
    if not isinstance(item, dict):
        return None
    item_type = item.get("type")
    if item_type == "text":
        text = item.get("text", "")
        return {"type": "input_text", "text": text} if text else None
    if item_type == "image_url":
        return item
    if item_type == "image":
        src = item.get("source") or {}
        if src.get("type") == "base64" and src.get("data"):
            return {
                "type": "input_image",
                "image_url": f"data:{src.get('media_type', 'image/png')};base64,{src.get('data', '')}",
            }
    return None


def _history_to_responses_input(messages):
    items = []
    for message in messages:
        role = message.get("role")
        blocks = message.get("content") or []
        if not isinstance(blocks, list):
            blocks = [{"type": "text", "text": str(blocks)}]
        text_like = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if role == "assistant" and block_type == "tool_use":
                if text_like:
                    items.append({"role": "assistant", "content": list(text_like)})
                    text_like = []
                items.append(
                    {
                        "type": "function_call",
                        "call_id": block.get("id", ""),
                        "name": block.get("name", ""),
                        "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
                    }
                )
                continue
            if role == "user" and block_type == "tool_result":
                if text_like:
                    items.append({"role": "user", "content": list(text_like)})
                    text_like = []
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": block.get("tool_use_id", ""),
                        "output": _stringify_tool_result_content(block.get("content", "")),
                    }
                )
                continue
            if block_type == "thinking":
                continue
            mapped = _content_item_to_input_item(block)
            if mapped:
                text_like.append(mapped)
        if text_like:
            items.append({"role": role, "content": text_like})
    return items


def _iter_response_output_items(response):
    if response is None:
        return []
    if isinstance(response, dict):
        return response.get("output") or []
    output = getattr(response, "output", None)
    return output or []


def _normalize_response_content_item(item):
    if item is None:
        return None
    if isinstance(item, dict):
        return item
    data = {}
    for key in ("type", "text", "output_text", "input_text"):
        value = getattr(item, key, None)
        if value is not None:
            data[key] = value
    if data:
        return data
    text = _text_from_content_item(item)
    return {"type": "output_text", "text": text} if text else None


def _normalize_response_output_item(item):
    if item is None:
        return None
    if isinstance(item, dict):
        return item
    data = {}
    for key in ("type", "id", "call_id", "name", "arguments", "summary", "content", "text"):
        value = getattr(item, key, None)
        if value is not None:
            data[key] = value
    content = data.get("content")
    if isinstance(content, list):
        normalized = []
        for sub_item in content:
            normalized_sub_item = _normalize_response_content_item(sub_item)
            if normalized_sub_item:
                normalized.append(normalized_sub_item)
        data["content"] = normalized
    elif content is not None:
        text = _collect_text_from_content(content)
        data["content"] = [{"type": "output_text", "text": text}] if text else []
    return data or None


def _responses_output_to_blocks(output_items):
    normalized_items = []
    text_parts = []
    thinking_parts = []
    tool_calls = []

    for item in output_items or []:
        normalized = _normalize_response_output_item(item)
        if not normalized:
            continue
        normalized_items.append(normalized)
        item_type = normalized.get("type")
        if item_type == "function_call":
            tool_calls.append(
                MockToolCall(
                    normalized.get("name", ""),
                    _parse_jsonish_arguments(normalized.get("arguments", "")),
                    id=normalized.get("call_id") or normalized.get("id", ""),
                )
            )
            continue
        if item_type == "reasoning":
            summary = normalized.get("summary")
            if isinstance(summary, list):
                for part in summary:
                    text = _text_from_content_item(part)
                    if text:
                        thinking_parts.append(text)
            else:
                text = _text_from_content_item(summary) or _text_from_content_item(normalized)
                if text:
                    thinking_parts.append(text)
            continue

        content = normalized.get("content")
        if isinstance(content, list):
            for content_item in content:
                content_type = content_item.get("type")
                text = _text_from_content_item(content_item)
                if not text:
                    continue
                if content_type == "reasoning":
                    thinking_parts.append(text)
                else:
                    text_parts.append(text)
            continue

        text = _text_from_content_item(normalized)
        if text:
            text_parts.append(text)

    blocks = _build_content_blocks(
        "".join(text_parts).strip(),
        "\n".join(part.strip() for part in thinking_parts if part and part.strip()).strip(),
        [{"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.args} for tc in tool_calls],
    )
    return {
        "blocks": blocks,
        "content": "\n".join(part for part in text_parts if part).strip(),
        "thinking": "\n".join(part.strip() for part in thinking_parts if part and part.strip()).strip(),
        "tool_calls": tool_calls,
        "normalized_output": normalized_items,
    }


def _text_tool_instruction(tools):
    tools_json = json.dumps(tools, ensure_ascii=False, separators=(",", ":"))
    return (
        "\n\n### Tool calling fallback\n"
        "Native tool calling is unavailable for this provider. If a tool is needed, "
        "output one or more tool calls exactly as:\n"
        '<tool_use>{"name":"tool_name","arguments":{...}}</tool_use>\n'
        "Then stop and wait for tool results.\n"
        f"Available tools:\n{tools_json}\n"
    )


def _messages_with_text_tool_instruction(messages, tools):
    instruction = _text_tool_instruction(tools)
    if messages and messages[0].get("role") == "system":
        first = dict(messages[0])
        first["content"] = str(first.get("content", "")) + instruction
        return [first] + list(messages[1:])
    return [{"role": "system", "content": instruction.strip()}] + list(messages)


def _is_native_tool_rejection(exc):
    text = str(exc)
    return (
        "tools[0]" in text
        and "unknown variant" in text
        and ("custom" in text or "web_search" in text)
    )


def _litellm_completion_kwargs(sess, messages):
    kwargs = {
        "model": _litellm_model_name(sess),
        "messages": messages,
        "api_key": sess.api_key,
        "api_base": sess.api_base,
        "stream": sess.stream,
        "timeout": sess.read_timeout,
    }
    if sess.temperature is not None:
        kwargs["temperature"] = sess.temperature
    if sess.max_tokens is not None:
        kwargs["max_tokens"] = sess.max_tokens
    if sess.max_retries is not None:
        kwargs["num_retries"] = sess.max_retries
    if sess.reasoning_effort:
        kwargs["reasoning_effort"] = sess.reasoning_effort
    if sess.service_tier:
        kwargs["service_tier"] = sess.service_tier
    tools = getattr(sess, "tools", None)
    if tools:
        kwargs["tools"] = tools
    if sess.stream:
        kwargs["stream_options"] = {"include_usage": True}
    return kwargs


def _yield_from_litellm_response(sess, response):
    if not sess.stream:
        choice = (getattr(response, "choices", None) or [None])[0]
        message = getattr(choice, "message", None) if choice else None
        text = _message_text_content(message)
        reasoning = _extract_reasoning_from_obj(message)
        tool_blocks = _tool_blocks_from_message(message)
        if text:
            yield text
        usage = getattr(response, "usage", None)
        if usage:
            sess.last_usage = usage
            # sess.logger.record_usage(usage)
            #todo 打印到终端，方便调试查看
            logging.info("[Usage] %s", usage)
        return _build_content_blocks(text, reasoning, tool_blocks)

    text_parts = []
    reasoning_parts = []
    tool_map = {}
    for chunk in response:
        usage = getattr(chunk, "usage", None)
        if usage:
            sess.last_usage = usage
            # todo 打印到终端，方便调试查看
            # sess.logger.record_usage(usage)
            logging.info("[Usage] %s", usage)

        choices = getattr(chunk, "choices", None) or []
        if not choices:
            continue

        delta = getattr(choices[0], "delta", None)
        if delta is None:
            continue

        reasoning = _extract_reasoning_from_obj(delta)
        if reasoning:
            reasoning_parts.append(reasoning)

        text = _text_from_delta_content(getattr(delta, "content", None))
        if text:
            text_parts.append(text)
            yield text

        for delta_tc in getattr(delta, "tool_calls", None) or []:
            _merge_stream_tool_call(tool_map, delta_tc)

    return _build_content_blocks(
        "".join(text_parts),
        "".join(reasoning_parts).strip(),
        _tool_blocks_from_map(tool_map),
    )


def _litellm_raw_ask(sess, messages):
    try:
        from litellm import completion
    except ImportError:
        yield "!!!Error: litellm is not installed"
        return []

    kwargs = _litellm_completion_kwargs(sess, messages)

    try:
        response = completion(**kwargs)
    except Exception as exc:
        if kwargs.get("tools") and _is_native_tool_rejection(exc):
            fallback_messages = _messages_with_text_tool_instruction(messages, kwargs["tools"])
            fallback_kwargs = _litellm_completion_kwargs(sess, fallback_messages)
            fallback_kwargs.pop("tools", None)
            try:
                response = completion(**fallback_kwargs)
            except Exception as retry_exc:
                yield f"!!!Error: {retry_exc}"
                return []
        else:
            yield f"!!!Error: {exc}"
            return []

    return (yield from _yield_from_litellm_response(sess, response))


def _is_error_chunk(chunk):
    return isinstance(chunk, str) and chunk.lstrip().startswith(("!!!Error:", "[Error:"))


def _is_partial_stream_warning(chunk):
    return isinstance(chunk, str) and "[!!! 流异常中断" in chunk


def _resolve_backend(session_or_client):
    return getattr(session_or_client, "backend", session_or_client)


def _session_to_router_model(session, alias):
    return {
        "model_name": alias,
        "litellm_params": {
            "model": session.model,
            "api_key": session.api_key,
            "api_base": session.api_base,
            "timeout": session.read_timeout,
            "stream": session.stream,
        },
    }


class BaseSession:
    def __init__(self, cfg):
        self.api_key = cfg["apikey"]
        self.api_base = cfg["apibase"].rstrip("/")
        self.model = cfg.get("model", "")
        self.context_win = cfg.get("context_win", 28000)
        self.history = []
        self.lock = threading.Lock()
        self.system = ""
        self.name = cfg.get("name", self.model)
        self.provider = cfg.get("provider")
        self.custom_llm_provider = cfg.get("custom_llm_provider")# provider 用来链接?router?
        self.max_retries = max(0, int(cfg.get("max_retries", 4)))
        self.stream = cfg.get("stream", True)
        self.read_timeout = max(5, int(cfg.get("read_timeout", 30 if self.stream else 240)))
        self.reasoning_effort = cfg.get("reasoning_effort")
        self.service_tier = cfg.get("service_tier")
        self.thinking_type = cfg.get("thinking_type")
        self.thinking_budget_tokens = cfg.get("thinking_budget_tokens")
        self.temperature = cfg.get("temperature", 1)
        self.max_tokens = cfg.get("max_tokens")
        self.logger = LLMLogger()
        self.last_usage = None
        # 将session属性重新构建,并设置client值,同时
        self.tools = None

    def ask(self, prompt):
        def _ask_gen():
            with self.lock:
                self.history.append({"role": "user", "content": [{"type": "text", "text": prompt}]})
                trim_messages_history(self.history, self.context_win)
                messages = self.make_messages(self.history)
            content_blocks = None
            content = ""
            gen = self.raw_ask(messages)
            try:
                while True:
                    chunk = next(gen)
                    content += chunk
                    yield chunk
            except StopIteration as stop:
                content_blocks = stop.value or []
            for block in content_blocks:
                if block.get("type") == "tool_use":
                    tool_call = {"name": block.get("name", ""), "arguments": block.get("input", {})}
                    yield f"<tool_use>{json.dumps(tool_call, ensure_ascii=False)}</tool_use>"
            if not content.startswith("!!!Error:"):
                self.history.append({"role": "assistant", "content": content_blocks or [{"type": "text", "text": content}]})

        return _ask_gen() if self.stream else "".join(list(_ask_gen()))


class ClaudeSession(BaseSession):
    def raw_ask(self, messages):
        return (yield from _litellm_raw_ask(self, _msgs_claude2oai(messages)))

    def make_messages(self, raw_list):
        msgs = _drop_unsigned_thinking(
            [{"role": message["role"], "content": list(message["content"])} for message in raw_list]
        )
        return msgs


class LLMSession(BaseSession):
    def raw_ask(self, messages):
        return (yield from _litellm_raw_ask(self, messages))

    def make_messages(self, raw_list):
        return _msgs_claude2oai(raw_list)


class NativeOAISession(BaseSession):
    def make_messages(self, raw_list):
        return [{"role": item["role"], "content": list(item["content"])} for item in raw_list]

    def _prepare_responses_tools(self):
        return self.tools or None

    def _build_query_from_history(self, history):
        fixed = _fix_messages(self.make_messages(history))
        fixed = _ensure_thinking_blocks(fixed, self.model)
        query = {
            "model": _litellm_model_name(self),
            "input": _history_to_responses_input(fixed),
            "api_key": self.api_key,
            "api_base": self.api_base,
            "stream": self.stream,
            "timeout": self.read_timeout,
        }
        if self.system:
            query["instructions"] = self.system
        tools = self._prepare_responses_tools()
        if tools:
            query["tools"] = tools
        if self.temperature is not None:
            query["temperature"] = self.temperature
        if self.max_tokens is not None:
            query["max_output_tokens"] = self.max_tokens
        if self.max_retries is not None:
            query["num_retries"] = self.max_retries
        if self.reasoning_effort:
            query["reasoning_effort"] = self.reasoning_effort
        if self.service_tier:
            query["service_tier"] = self.service_tier
        return query

    def raw_ask(self, query):
        try:
            import litellm
        except ImportError:
            yield "!!!Error: litellm is not installed"
            return {"output": []}

        responder = getattr(litellm, "responses", None) or getattr(litellm, "response", None)
        if responder is None:
            yield "!!!Error: litellm.responses is not available"
            return {"output": []}

        try:
            response = responder(**query)
        except Exception as exc:
            yield f"!!!Error: {exc}"
            return {"output": []}

        if not self.stream:
            usage = getattr(response, "usage", None) if not isinstance(response, dict) else response.get("usage")
            usage_dict = _response_usage_dict(usage)
            if usage_dict:
                self.last_usage = usage_dict
                logging.info("[Usage] %s", usage_dict)
            text = _responses_output_to_blocks(_iter_response_output_items(response)).get("content", "")
            if text:
                yield text
            return response

        output_items = []
        usage_dict = {}
        for chunk in response:
            if isinstance(chunk, dict) and chunk.get("output"):
                output_items.extend(chunk.get("output") or [])
            chunk_output = getattr(chunk, "output", None)
            if chunk_output:
                output_items.extend(chunk_output)

            usage = getattr(chunk, "usage", None) if not isinstance(chunk, dict) else chunk.get("usage")
            parsed_usage = _response_usage_dict(usage)
            if parsed_usage:
                usage_dict = parsed_usage
                self.last_usage = parsed_usage
                logging.info("[Usage] %s", parsed_usage)

            delta_text = ""
            if isinstance(chunk, dict):
                delta_text = (
                    chunk.get("output_text")
                    or chunk.get("delta")
                    or chunk.get("text")
                    or chunk.get("content", "")
                )
            else:
                for attr in ("output_text", "delta", "text"):
                    value = getattr(chunk, attr, None)
                    if isinstance(value, str) and value:
                        delta_text = value
                        break
                if not delta_text:
                    delta_text = _collect_text_from_content(getattr(chunk, "content", None))
            if delta_text:
                yield delta_text

        return {"output": output_items, "usage": usage_dict}

    def _normalize_responses_response(self, response):
        usage = {}
        if isinstance(response, dict):
            usage = _response_usage_dict(response.get("usage"))
        else:
            usage = _response_usage_dict(getattr(response, "usage", None))
        if usage:
            self.last_usage = usage

        parsed = _responses_output_to_blocks(_iter_response_output_items(response))
        blocks = parsed["blocks"]
        content = parsed["content"]
        tool_calls = parsed["tool_calls"]
        thinking = parsed["thinking"]
        if not tool_calls:
            tool_calls, content = _parse_text_tool_calls(content)
        if not thinking:
            thinking, content = extract_thinking(content)
        if not blocks and content:
            blocks = [{"type": "text", "text": content}]
        return {
            "assistant_blocks": blocks,
            "content": content,
            "thinking": thinking,
            "tool_calls": tool_calls,
            "usage": usage or self.last_usage or {},
            "raw": _response_to_raw_string(response),
        }

    def ask(self, msg):
        assert isinstance(msg, dict)
        with self.lock:
            self.history.append(msg)
            trim_messages_history(self.history, self.context_win)
            query = self._build_query_from_history(self.history)
        gen = self.raw_ask(query)
        response = None
        try:
            while True:
                yield next(gen)
        except StopIteration as stop:
            response = stop.value
        normalized = self._normalize_responses_response(response)
        blocks = normalized["assistant_blocks"]
        if blocks and not (
            len(blocks) == 1 and blocks[0].get("text", "").startswith("!!!Error:")
        ):
            self.history.append({"role": "assistant", "content": blocks})
        return MockResponse(
            thinking=normalized["thinking"],
            content=normalized["content"],
            tool_calls=normalized["tool_calls"],
            raw=normalized["raw"],
            usage=normalized["usage"],
        )


class NativeClaudeSession(BaseSession):
    def raw_ask(self, messages):
        fixed = _ensure_thinking_blocks(_drop_unsigned_thinking(_fix_messages(messages)), self.model)
        completion_messages = _msgs_claude2oai(fixed)
        if self.system:
            completion_messages = [{"role": "system", "content": self.system}] + completion_messages
        return (yield from _litellm_raw_ask(self, completion_messages))

    def ask(self, msg):
        assert isinstance(msg, dict)
        with self.lock:
            self.history.append(msg)
            trim_messages_history(self.history, self.context_win)
            messages = [{"role": item["role"], "content": list(item["content"])} for item in self.history]
        gen = self.raw_ask(messages)
        content_blocks = None
        try:
            while True:
                yield next(gen)
        except StopIteration as stop:
            content_blocks = stop.value or []
        if content_blocks and not (
            len(content_blocks) == 1 and content_blocks[0].get("text", "").startswith("!!!Error:")
        ):
            self.history.append({"role": "assistant", "content": content_blocks})
        text_parts = [block["text"] for block in content_blocks if block.get("type") == "text"]
        content = "\n".join(text_parts).strip()
        tool_calls = [
            MockToolCall(block["name"], block.get("input", {}), id=block.get("id", ""))
            for block in content_blocks
            if block.get("type") == "tool_use"
        ]
        if not tool_calls:
            tool_calls, content = _parse_text_tool_calls(content)
        thinking = "\n".join(
            block["thinking"] for block in content_blocks if block.get("type") == "thinking"
        ).strip()
        if not thinking:
            thinking, content = extract_thinking(content)
        return MockResponse(
            thinking=thinking,
            content=content,
            tool_calls=tool_calls,
            raw=str(content_blocks),
            usage=self.last_usage or {},
        )


class MixinSession:
    """LiteLLM-backed multi-session fallback with spring-back support."""

    _BROADCAST_ATTRS = frozenset(
        {
            "system",
            "tools",
            "temperature",
            "max_tokens",
            "reasoning_effort",
            "history",
        }
    )

    def __init__(self, all_sessions, cfg):
        self._retries = cfg.get("max_retries", 3)
        self._base_delay = cfg.get("base_delay", 1.5)
        self._spring_sec = cfg.get("spring_back", 300)
        self._sessions = self._resolve_sessions(all_sessions, cfg)
        self.name = "|".join(session.name for session in self._sessions)
        self.model = getattr(self._sessions[0], "model", None)
        self._cur_idx = 0
        self._switched_at = 0.0
        self._orig_raw_asks = [session.raw_ask for session in self._sessions]
        for session in self._sessions:
            session.max_retries = 0
        self._sessions[0].raw_ask = self._raw_ask
        self._router_model_group = cfg.get("router_model_group", self.name.replace("|", "_"))
        self._router = self._build_router()

    def _resolve_sessions(self, all_sessions, cfg):
        selected = []
        for item in cfg.get("llm_nos", []):
            if isinstance(item, int):
                selected.append(_resolve_backend(all_sessions[item]))
                continue
            for session in all_sessions:
                backend = _resolve_backend(session)
                if getattr(backend, "name", None) == item:
                    selected.append(backend)
                    break
            else:
                raise ValueError(f"Unknown session {item!r}")
        if not selected:
            raise ValueError("MixinSession requires at least one backend")
        return [copy(session) for session in selected]

    def _build_router(self):
        try:
            from litellm import Router
        except ImportError:
            return None
        try:
            return Router(
                model_list=[
                    _session_to_router_model(session, self._router_model_group)
                    for session in self._sessions
                ]
            )
        except Exception:
            return None

    def __getattr__(self, name):
        return getattr(self._sessions[0], name)

    def __setattr__(self, name, value):
        if name in self._BROADCAST_ATTRS and "_sessions" in self.__dict__:
            for session in self._sessions:
                setattr(session, name, value)
            return
        object.__setattr__(self, name, value)

    @property
    def primary(self):
        return self._sessions[0]

    def _pick(self):
        if self._cur_idx and time.time() - self._switched_at > self._spring_sec:
            self._cur_idx = 0
        return self._cur_idx

    def _router_raw_ask(self, messages):
        if self._router is None:
            yield "!!!Error: litellm router is not available"
            return []
        kwargs = _litellm_completion_kwargs(self.primary, messages)
        kwargs["model"] = self._router_model_group
        try:
            response = self._router.completion(**kwargs)
        except Exception as exc:
            yield f"!!!Error: {exc}"
            return []
        return (yield from _yield_from_litellm_response(self.primary, response))

    def _raw_ask(self, *args, **kwargs):
        base = self._pick()
        total = len(self._sessions)

        if self._router is not None and total > 1:
            gen = self._router_raw_ask(*args, **kwargs)
            last_chunk = None
            try:
                while True:
                    last_chunk = next(gen)
                    yield last_chunk
            except StopIteration as stop:
                if not _is_error_chunk(last_chunk):
                    return stop.value or []

        for attempt in range(self._retries + 1):
            idx = (base + attempt) % total
            gen = self._orig_raw_asks[idx](*args, **kwargs)
            print(f"[MixinSession] Using session ({self._sessions[idx].name})")
            last_chunk = None
            yielded = False
            try:
                while True:
                    chunk = next(gen)
                    last_chunk = chunk
                    if not yielded and _is_error_chunk(chunk):
                        continue
                    yield chunk
                    yielded = True
            except StopIteration as stop:
                return_val = stop.value or []
            else:
                return_val = []

            if not _is_error_chunk(last_chunk):
                if attempt > 0:
                    self._cur_idx = idx
                    self._switched_at = time.time()
                elif _is_partial_stream_warning(last_chunk) and total > 1:
                    self._cur_idx = (idx + 1) % total
                    self._switched_at = time.time()
                    print(
                        f"[MixinSession] Partial failure, next call -> "
                        f"s{self._cur_idx} ({self._sessions[self._cur_idx].name})"
                    )
                return return_val

            if attempt >= self._retries:
                if last_chunk:
                    yield last_chunk
                return return_val

            next_idx = (base + attempt + 1) % total
            if next_idx == base:
                round_no = (attempt + 1) // total
                delay = min(30, self._base_delay * (1.5 ** round_no))
                print(
                    f"[MixinSession] {str(last_chunk)[:80]}, "
                    f"round {round_no} exhausted, retry in {delay:.1f}s"
                )
                time.sleep(delay)
            else:
                print(
                    f"[MixinSession] {str(last_chunk)[:80]}, "
                    f"retry {attempt + 1}/{self._retries} (s{idx}->s{next_idx})"
                )


class ToolClient:
    def __init__(self, backend, auto_save_tokens=True):
        self.backend = backend
        self.auto_save_tokens = auto_save_tokens
        self.last_tools = ""
        self.name = self.backend.name
        self.total_cd_tokens = 0
        self.logger = LLMLogger()

    def chat(self, messages, tools=None):
        full_prompt = self._build_protocol_prompt(messages, tools)
        gen = self.backend.ask(full_prompt)
        self.logger.write("Prompt", full_prompt)
        raw_text = ""
        for chunk in gen:
            raw_text += chunk
            yield chunk
        self.logger.write("Response", raw_text)
        return self._parse_mixed_response(raw_text)

    def _prepare_tool_instruction(self, tools):
        if not tools:
            return ""
        tools_json = json.dumps(tools, ensure_ascii=False, separators=(",", ":"))
        is_en = os.environ.get("GA_LANG") == "en"
        if is_en:
            tool_instruction = """
### Interaction Protocol (must follow strictly, always in effect)
Follow these steps to think and act:
1. **Think**: Analyze the current situation and strategy inside `<thinking>` tags.
2. **Summarize**: Output a minimal one-line (<30 words) physical snapshot in `<summary>`: new info from last tool result + current tool call intent.
3. **Act**: If you need to call tools, output one or more **<tool_use> blocks** after your reply, then stop.
"""
        else:
            tool_instruction = """
### 交互协议 (必须严格遵守，持续有效)
请按照以下步骤思考并行动：
1. **思考**: 在 `<thinking>` 标签中先进行思考，分析现状和策略。
2. **总结**: 在 `<summary>` 中输出极短单行（<30字）物理快照，包括上次结果新信息+本次工具调用意图。
3. **行动**: 如需调用工具，请在回复正文之后输出一个或多个 `<tool_use>` 块，然后结束。
"""
        tool_instruction += (
            f'\nFormat: ```<tool_use>{{"name": "tool_name", "arguments": {{...}}}}</tool_use>```\n'
            f"\n### Tools (mounted, always in effect):\n{tools_json}\n"
        )
        if self.auto_save_tokens and self.last_tools == tools_json:
            tool_instruction = (
                "\n### Tools: still active, ready to call. Protocol unchanged.\n"
                if is_en
                else "\n### 工具库状态：持续有效，可正常调用。调用协议沿用。\n"
            )
        else:
            self.total_cd_tokens = 0
        self.last_tools = tools_json
        return tool_instruction

    def _build_protocol_prompt(self, messages, tools):
        system_content = next((message["content"] for message in messages if message["role"].lower() == "system"), "")
        history_msgs = [message for message in messages if message["role"].lower() != "system"]
        system = f"{system_content}\n" if system_content else ""
        system += self._prepare_tool_instruction(tools)
        user = ""
        for message in history_msgs:
            role = "USER" if message["role"] == "user" else "ASSISTANT"
            user += f"=== {role} ===\n"
            for tool_result in message.get("tool_results", []):
                user += f'<tool_result>{tool_result["content"]}</tool_result>\n'
            user += str(message["content"]) + "\n"
            self.total_cd_tokens += len(user) // 3
        if self.total_cd_tokens > 9000:
            self.last_tools = ""
        user += "=== ASSISTANT ===\n"
        return system + user

    def _parse_mixed_response(self, text):
        remaining_text = text
        thinking, remaining_text = extract_thinking(text)
        tool_calls, remaining_text = _parse_text_tool_calls(remaining_text)
        if not tool_calls:
            errors = []
            json_strs = []
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
            if not tool_calls:
                for error in errors:
                    tool_calls.append(MockToolCall("bad_json", {"msg": error}))
        return MockResponse(thinking=thinking, content=remaining_text.strip(), tool_calls=tool_calls, raw=text)


THINKING_PROMPT_ZH = """
### 行动规范（持续有效）
每次回复（含工具调用轮）都先在回复文字中包含一个<summary></summary> 中输出极简单行（<30字）物理快照：上次结果新信息+本次意图。此内容进入长期工作记忆。

若用户需求未完成，必须进行工具调用。
""".strip()

THINKING_PROMPT_EN = """
### Action Protocol (always in effect)
The reply body should first include a minimal one-line (<30 words) physical snapshot in <summary></summary>: new info from last result + current intent. This goes into long-term working memory.

If the user's request is not yet complete, tool calls are required.
""".strip()


class NativeToolClient:
    @staticmethod
    def _thinking_prompt():
        return THINKING_PROMPT_EN if os.environ.get("GA_LANG") == "en" else THINKING_PROMPT_ZH

    def __init__(self, backend):
        self.backend = backend
        self.backend.system = self._thinking_prompt()
        self.name = self.backend.name
        self._pending_tool_ids = []
        self.logger = LLMLogger()

    def set_system(self, extra_system):
        combined = f"{extra_system}\n\n{self._thinking_prompt()}" if extra_system else self._thinking_prompt()
        self.backend.system = combined

    def chat(self, messages, tools=None):
        if tools:
            self.backend.tools = tools
        combined_content = []
        tool_results = []
        for message in messages:
            content = message.get("content", "")
            if message["role"] == "system":
                self.set_system(content)
                continue
            if isinstance(content, str):
                combined_content.append({"type": "text", "text": content})
            elif isinstance(content, list):
                combined_content.extend(content)
            if message["role"] == "user" and message.get("tool_results"):
                tool_results.extend(message["tool_results"])
        tr_id_set = set()
        tool_result_blocks = []
        for tool_result in tool_results:
            tool_use_id = tool_result.get("tool_use_id", "")
            content = tool_result.get("content", "")
            tr_id_set.add(tool_use_id)
            if tool_use_id:
                tool_result_blocks.append(
                    {"type": "tool_result", "tool_use_id": tool_use_id, "content": tool_result.get("content", "")}
                )
            else:
                combined_content = [{"type": "text", "text": f"<tool_result>{content}</tool_result>"}] + combined_content
        for tool_id in self._pending_tool_ids:
            if tool_id not in tr_id_set:
                tool_result_blocks.append({"type": "tool_result", "tool_use_id": tool_id, "content": ""})
        self._pending_tool_ids = []

        merged = {"role": "user", "content": tool_result_blocks + combined_content}
        self.logger.write("Prompt", json.dumps(merged, ensure_ascii=False, indent=2))
        gen = self.backend.ask(merged)
        resp = None
        try:
            while True:
                yield next(gen)
        except StopIteration as stop:
            resp = stop.value
        if resp:
            self.logger.write("Response", str(resp.raw))
        if resp and getattr(resp, "tool_calls", None):
            self._pending_tool_ids = [tool_call.id for tool_call in resp.tool_calls]
        return resp


__all__ = [
    "_msgs_claude2oai",
    "_drop_unsigned_thinking",
    "_ensure_thinking_blocks",
    "_parse_text_tool_calls",
    "openai_tools_to_claude",
    "BaseSession",
    "ClaudeSession",
    "LLMSession",
    "MixinSession",
    "NativeClaudeSession",
    "NativeOAISession",
    "ToolClient",
    "NativeToolClient",
]
