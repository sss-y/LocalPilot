import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.session import (
    ClaudeSession,
    LLMSession,
    MixinSession,
    NativeClaudeSession,
    NativeToolClient,
    ToolClient,
    _msgs_claude2oai,
    _parse_text_tool_calls,
    openai_tools_to_claude,
)


class DummyFunction:
    def __init__(self, name=None, arguments=None):
        self.name = name
        self.arguments = arguments


class DummyToolCall:
    def __init__(self, index=0, id="", name=None, arguments=None):
        self.index = index
        self.id = id
        self.function = DummyFunction(name=name, arguments=arguments)


class DummyDelta:
    def __init__(self, content=None, reasoning_content=None, tool_calls=None):
        self.content = content
        self.reasoning_content = reasoning_content
        self.tool_calls = tool_calls or []


class DummyChoice:
    def __init__(self, delta=None, message=None):
        self.delta = delta
        self.message = message


class DummyChunk:
    def __init__(self, delta=None, usage=None):
        self.choices = [DummyChoice(delta=delta)]
        self.usage = usage


class DummyMessage:
    def __init__(self, content="", reasoning_content="", tool_calls=None):
        self.content = content
        self.reasoning_content = reasoning_content
        self.tool_calls = tool_calls or []


class DummyResponse:
    def __init__(self, message, usage=None):
        self.choices = [DummyChoice(message=message)]
        self.usage = usage


def make_cfg(stream=True):
    return {
        "apikey": "test-key",
        "apibase": "https://mock.example.com/v1",
        "model": "mock-model",
        "stream": stream,
        "max_retries": 1,
        "read_timeout": 10,
    }


def consume_generator(gen):
    chunks = []
    try:
        while True:
            chunks.append(next(gen))
    except StopIteration as stop:
        return chunks, stop.value


class BackendHolder:
    def __init__(self, backend):
        self.backend = backend


class FallbackBackend:
    def __init__(self, name, chunks, return_blocks=None):
        self.name = name
        self.model = name
        self.api_key = "k"
        self.api_base = "https://mock.example.com/v1"
        self.read_timeout = 10
        self.stream = True
        self.max_retries = 0
        self.temperature = 1
        self.max_tokens = None
        self.reasoning_effort = None
        self.service_tier = None
        self.history = []
        self.system = ""
        self.tools = None
        self._chunks = chunks
        self._return_blocks = return_blocks or []

    def raw_ask(self, messages):
        for chunk in self._chunks:
            yield chunk
        return self._return_blocks


class SessionLiteLLMTests(unittest.TestCase):
    def test_msgs_claude2oai_converts_internal_blocks(self):
        messages = [
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "plan"},
                    {"type": "text", "text": "answer"},
                    {"type": "tool_use", "id": "t1", "name": "read_file", "input": {"path": "a.txt"}},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "show me"},
                    {"type": "tool_result", "tool_use_id": "t1", "content": "ok"},
                ],
            },
        ]

        converted = _msgs_claude2oai(messages)

        self.assertEqual(converted[0]["role"], "assistant")
        self.assertEqual(converted[0]["reasoning_content"], "plan")
        self.assertEqual(converted[0]["tool_calls"][0]["function"]["name"], "read_file")
        self.assertEqual(converted[1]["role"], "user")
        self.assertEqual(converted[2]["role"], "tool")
        self.assertEqual(converted[2]["tool_call_id"], "t1")

    def test_llm_session_raw_ask_streams_text_and_tool_blocks(self):
        fake_module = types.SimpleNamespace(
            completion=lambda **kwargs: iter(
                [
                    DummyChunk(delta=DummyDelta(reasoning_content="thinking ")),
                    DummyChunk(delta=DummyDelta(content="hello ")),
                    DummyChunk(
                        delta=DummyDelta(
                            content="world",
                            tool_calls=[
                                DummyToolCall(index=0, id="tool_1", name="read_file", arguments='{"path":"README.md"}')
                            ],
                        ),
                        usage={"total_tokens": 12},
                    ),
                ]
            )
        )
        session = LLMSession(make_cfg(stream=True))

        with patch.dict(sys.modules, {"litellm": fake_module}):
            chunks, blocks = consume_generator(session.raw_ask([{"role": "user", "content": "hi"}]))

        self.assertEqual(chunks, ["hello ", "world"])
        self.assertEqual(
            blocks,
            [
                {"type": "thinking", "thinking": "thinking"},
                {"type": "text", "text": "hello world"},
                {"type": "tool_use", "id": "tool_1", "name": "read_file", "input": {"path": "README.md"}},
            ],
        )
        self.assertEqual(session.last_usage, {"total_tokens": 12})

    def test_claude_session_raw_ask_uses_same_compatible_output_shape(self):
        fake_module = types.SimpleNamespace(
            completion=lambda **kwargs: DummyResponse(
                DummyMessage(content="plain reply", reasoning_content="brief think"),
                usage={"prompt_tokens": 3, "completion_tokens": 2},
            )
        )
        session = ClaudeSession(make_cfg(stream=False))
        messages = [
            {
                "role": "user",
                "content": [{"type": "text", "text": "hello"}],
            }
        ]

        with patch.dict(sys.modules, {"litellm": fake_module}):
            chunks, blocks = consume_generator(session.raw_ask(messages))

        self.assertEqual(chunks, ["plain reply"])
        self.assertEqual(
            blocks,
            [
                {"type": "thinking", "thinking": "brief think"},
                {"type": "text", "text": "plain reply"},
            ],
        )
        self.assertEqual(session.last_usage, {"prompt_tokens": 3, "completion_tokens": 2})

    def test_mixin_session_falls_back_to_second_backend(self):
        primary = BackendHolder(FallbackBackend("primary", ["!!!Error: boom"]))
        secondary = BackendHolder(
            FallbackBackend(
                "secondary",
                ["ok from backup"],
                [{"type": "text", "text": "ok from backup"}],
            )
        )
        mixin = MixinSession(
            [primary, secondary],
            {"llm_nos": [0, 1], "max_retries": 1, "spring_back": 300},
        )

        chunks, blocks = consume_generator(mixin.primary.raw_ask([{"role": "user", "content": "hi"}]))

        self.assertEqual(chunks, ["ok from backup"])
        self.assertEqual(blocks, [{"type": "text", "text": "ok from backup"}])
        self.assertEqual(mixin._cur_idx, 1)

    def test_mixin_session_springs_back_to_primary_after_window(self):
        primary = BackendHolder(
            FallbackBackend(
                "primary",
                ["primary reply"],
                [{"type": "text", "text": "primary reply"}],
            )
        )
        secondary = BackendHolder(
            FallbackBackend(
                "secondary",
                ["secondary reply"],
                [{"type": "text", "text": "secondary reply"}],
            )
        )
        mixin = MixinSession(
            [primary, secondary],
            {"llm_nos": [0, 1], "max_retries": 1, "spring_back": 1},
        )
        mixin._cur_idx = 1
        mixin._switched_at = 0

        with patch("core.session.time.time", return_value=999):
            chunks, blocks = consume_generator(mixin.primary.raw_ask([{"role": "user", "content": "hi"}]))

        self.assertEqual(chunks, ["primary reply"])
        self.assertEqual(blocks, [{"type": "text", "text": "primary reply"}])
        self.assertEqual(mixin._cur_idx, 0)

    def test_openai_tools_to_claude_converts_function_schema(self):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read file",
                    "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
                },
            }
        ]

        converted = openai_tools_to_claude(tools)

        self.assertEqual(converted[0]["name"], "read_file")
        self.assertIn("input_schema", converted[0])

    def test_parse_text_tool_calls_extracts_xml_tool_use(self):
        content = 'done<tool_use>{"name":"read_file","arguments":{"path":"README.md"}}</tool_use>'

        tool_calls, remaining = _parse_text_tool_calls(content)

        self.assertEqual(remaining, "done")
        self.assertEqual(tool_calls[0].function.name, "read_file")

    def test_tool_client_parses_text_protocol_response(self):
        class PromptBackend:
            name = "prompt"

            def ask(self, prompt):
                yield "ok "
                yield '<tool_use>{"name":"read_file","arguments":{"path":"README.md"}}</tool_use>'
                return []

        client = ToolClient(PromptBackend())

        gen = client.chat([{"role": "user", "content": "hello"}], tools=[])
        chunks, response = consume_generator(gen)

        self.assertEqual("".join(chunks), 'ok <tool_use>{"name":"read_file","arguments":{"path":"README.md"}}</tool_use>')
        self.assertEqual(response.content, "ok")
        self.assertEqual(response.tool_calls[0].function.name, "read_file")

    def test_native_tool_client_returns_mock_response(self):
        fake_module = types.SimpleNamespace(
            completion=lambda **kwargs: DummyResponse(
                DummyMessage(
                    content="done",
                    reasoning_content="think",
                    tool_calls=[DummyToolCall(id="tool_1", name="read_file", arguments='{"path":"README.md"}')],
                )
            )
        )
        backend = NativeClaudeSession(make_cfg(stream=False))
        client = NativeToolClient(backend)
        messages = [{"role": "user", "content": "hello"}]

        with patch.dict(sys.modules, {"litellm": fake_module}):
            chunks, response = consume_generator(client.chat(messages))

        self.assertEqual(chunks, ["done"])
        self.assertEqual(response.thinking, "think")
        self.assertEqual(response.tool_calls[0].function.name, "read_file")
        self.assertEqual(client._pending_tool_ids, ["tool_1"])


if __name__ == "__main__":
    unittest.main()
